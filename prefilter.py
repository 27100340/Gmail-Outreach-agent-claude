"""
Local pre-filter for Gmail outreach monitoring.

Batch-scans Gmail to identify which watched contacts have recent activity,
so only those contacts are sent to the Claude Managed Agent. This avoids
making 3 API calls per address when most contacts have no new activity.
"""

import re


def _extract_email(header_value):
    """Extract a bare email address from a header value like 'Name <user@example.com>'."""
    if not header_value:
        return ""
    match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", header_value)
    return match.group(0).lower() if match else header_value.strip().lower()


def _batch_search(gmail, addresses, query_template, batch_size=50):
    """
    Search Gmail for messages matching a query across many addresses.

    Batches addresses into groups of `batch_size`, joins each group with OR
    inside the query, runs the Gmail API search, and fetches metadata headers
    for each result message. Each result is matched back to the correct
    address in the batch.

    Parameters
    ----------
    gmail : googleapiclient.discovery.Resource
        Authenticated Gmail API service instance.
    addresses : list[str]
        Email addresses to search for.
    query_template : str
        Gmail search query with an ``{addr_group}`` placeholder that will be
        replaced by the OR-joined address group (e.g.
        ``"to:({addr_group}) is:sent newer_than:14d"``).
    batch_size : int
        How many addresses to combine into a single API search (default 50).

    Returns
    -------
    dict[str, list[dict]]
        Mapping of email address -> list of message metadata dicts.
        Each metadata dict has keys: id, threadId, subject, from, to, date,
        snippet.
    """
    results = {}
    for addr in addresses:
        results[addr.lower()] = []

    # Process addresses in batches
    for i in range(0, len(addresses), batch_size):
        batch = addresses[i : i + batch_size]
        addr_group = " OR ".join(batch)
        query = query_template.format(addr_group=addr_group)

        # Build a lowercase lookup set for this batch
        batch_lower = {a.lower() for a in batch}

        # Run the search — paginate to get all results
        page_token = None
        while True:
            search_args = {
                "userId": "me",
                "q": query,
                "maxResults": 200,
            }
            if page_token:
                search_args["pageToken"] = page_token

            response = gmail.users().messages().list(**search_args).execute()
            messages = response.get("messages", [])

            for msg in messages:
                detail = gmail.users().messages().get(
                    userId="me",
                    id=msg["id"],
                    format="metadata",
                    metadataHeaders=["Subject", "From", "To", "Date"],
                ).execute()

                headers = {
                    h["name"]: h["value"]
                    for h in detail.get("payload", {}).get("headers", [])
                }

                meta = {
                    "id": msg["id"],
                    "threadId": detail.get("threadId", msg.get("threadId", "")),
                    "subject": headers.get("Subject", "(no subject)"),
                    "from": headers.get("From", ""),
                    "to": headers.get("To", ""),
                    "date": headers.get("Date", ""),
                    "snippet": detail.get("snippet", ""),
                }

                # Match this message back to the correct address(es) in the batch
                from_addr = _extract_email(meta["from"])
                to_addrs_raw = meta["to"]
                to_addrs = {
                    _extract_email(part.strip())
                    for part in to_addrs_raw.split(",")
                    if part.strip()
                }

                matched = False
                # Check From against batch
                if from_addr in batch_lower:
                    results[from_addr].append(meta)
                    matched = True
                # Check To against batch
                for to_addr in to_addrs:
                    if to_addr in batch_lower and to_addr != from_addr:
                        results[to_addr].append(meta)
                        matched = True

                # Fallback: if no match found via headers, try substring matching
                if not matched:
                    for addr in batch:
                        addr_l = addr.lower()
                        if (
                            addr_l in from_addr
                            or addr_l in to_addrs_raw.lower()
                        ):
                            results[addr_l].append(meta)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    return results


def scan_watchlist(gmail, watchlist, console, status):
    """
    Batch-scan Gmail to classify watchlist contacts by activity level.

    Runs three scans:
    1. Sent to contacts (last 14 days)
    2. Received from contacts (last 14 days)
    3. Unread from contacts

    Then classifies each contact into one of:
    - **active**: has unread messages or new inbound in the last 14 days
    - **sent_no_reply**: we sent them email but received nothing back
    - **stale_thread**: had a conversation but they stopped replying
    - **no_response**: no response received (initial outreach sent via SendGrid)

    Parameters
    ----------
    gmail : googleapiclient.discovery.Resource
        Authenticated Gmail API service instance.
    watchlist : list[str]
        Email addresses to scan.
    console : rich.console.Console
        Rich console for logging.
    status : rich.status.Status
        Rich status spinner for progress updates.

    Returns
    -------
    dict
        Keys:
        - active_contacts: list of email addresses with activity
        - sent_no_reply: list of {email, subject, date_sent}
        - stale_threads: list of {email, subject, our_last_date, snippet}
        - no_response: list of email addresses with no response received
        - thread_ids: dict of {email: [threadId, ...]} for active contacts
    """
    total = len(watchlist)
    console.log(
        f"[blue]\u2192[/blue] Pre-filtering {total} contacts in batches of 50"
    )

    # ── Scan 1: Messages we sent to contacts (last 14 days) ──
    status.update("[yellow]Batch scanning sent emails...[/yellow]")
    sent_results = _batch_search(
        gmail,
        watchlist,
        "to:({addr_group}) is:sent newer_than:14d",
    )
    sent_count = sum(1 for msgs in sent_results.values() if msgs)
    console.log(
        f"[green]\u2713[/green] Sent scan complete \u2014 "
        f"found outbound to {sent_count}/{total} contacts"
    )

    # ── Scan 2: Messages received from contacts (last 14 days) ──
    status.update("[yellow]Batch scanning received emails...[/yellow]")
    received_results = _batch_search(
        gmail,
        watchlist,
        "from:({addr_group}) newer_than:14d",
    )
    received_count = sum(1 for msgs in received_results.values() if msgs)
    console.log(
        f"[green]\u2713[/green] Received scan complete \u2014 "
        f"found inbound from {received_count}/{total} contacts"
    )

    # ── Scan 3: Unread messages from contacts ──
    status.update("[yellow]Batch scanning unread emails...[/yellow]")
    unread_results = _batch_search(
        gmail,
        watchlist,
        "from:({addr_group}) is:unread",
    )
    unread_count = sum(1 for msgs in unread_results.values() if msgs)
    console.log(
        f"[green]\u2713[/green] Unread scan complete \u2014 "
        f"found unread from {unread_count}/{total} contacts"
    )

    # ── Classify each contact ──
    status.update("[yellow]Classifying contacts...[/yellow]")

    active_contacts = []
    sent_no_reply = []
    stale_threads = []
    no_response = []
    thread_ids = {}

    for addr in watchlist:
        addr_l = addr.lower()
        sent_msgs = sent_results.get(addr_l, [])
        received_msgs = received_results.get(addr_l, [])
        unread_msgs = unread_results.get(addr_l, [])

        has_sent = len(sent_msgs) > 0
        has_received = len(received_msgs) > 0
        has_unread = len(unread_msgs) > 0

        if has_unread or has_received:
            # Active: they have unread messages or sent us something recently
            active_contacts.append(addr)

            # Collect thread IDs the agent should read
            seen_threads = set()
            contact_threads = []
            for msg in unread_msgs + received_msgs + sent_msgs:
                tid = msg.get("threadId", "")
                if tid and tid not in seen_threads:
                    seen_threads.add(tid)
                    contact_threads.append(tid)
            thread_ids[addr] = contact_threads

        elif has_sent:
            # We sent them something but got nothing back — check if stale
            # Look for any received messages in sent threads (indicates prior
            # conversation that has gone quiet, vs. a brand new outreach)
            sent_thread_ids = {m.get("threadId") for m in sent_msgs if m.get("threadId")}

            # Check if any received message shares a thread with our sent messages.
            # Since received_msgs is empty here (has_received is False), this
            # contact either never replied (sent_no_reply) or had older activity
            # that's now outside the 14-day window (stale_thread).
            #
            # Heuristic: if we sent more than one message in the same thread,
            # it likely means we followed up — classify as stale_thread.
            threads_with_multiple_sent = {}
            for msg in sent_msgs:
                tid = msg.get("threadId", "")
                if tid:
                    threads_with_multiple_sent.setdefault(tid, []).append(msg)

            is_stale = any(
                len(msgs) > 1 for msgs in threads_with_multiple_sent.values()
            )

            if is_stale:
                # Pick the most recent sent message for the summary
                latest = max(sent_msgs, key=lambda m: m.get("date", ""))
                stale_threads.append({
                    "email": addr,
                    "subject": latest.get("subject", "(no subject)"),
                    "our_last_date": latest.get("date", ""),
                    "snippet": latest.get("snippet", ""),
                })
            else:
                # Single send, no reply
                latest = max(sent_msgs, key=lambda m: m.get("date", ""))
                sent_no_reply.append({
                    "email": addr,
                    "subject": latest.get("subject", "(no subject)"),
                    "date_sent": latest.get("date", ""),
                })

        else:
            # No activity found — outreach was sent via SendGrid, no response received
            no_response.append(addr)

    # ── Summary ──
    console.log(
        f"[green]\u2713[/green] Classification complete: "
        f"[bold]{len(active_contacts)}[/bold] active, "
        f"{len(sent_no_reply)} awaiting reply, "
        f"{len(stale_threads)} stale, "
        f"{len(no_response)} no response"
    )

    return {
        "active_contacts": active_contacts,
        "sent_no_reply": sent_no_reply,
        "stale_threads": stale_threads,
        "no_response": no_response,
        "thread_ids": thread_ids,
    }

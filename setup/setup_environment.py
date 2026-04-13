import anthropic
import json
import os

client = anthropic.Anthropic()

environment = client.beta.environments.create(
    name="gmail-monitor-env",
    config={
        "type": "cloud",
        "networking": {"type": "unrestricted"},
    },
)

# Save the environment ID
config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "agent_config.json")
with open(config_path, "r") as f:
    config = json.load(f)

config["environment_id"] = environment.id

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

print(f"Environment created successfully!")
print(f"Environment ID: {environment.id}")
print(f"Config saved to: {config_path}")
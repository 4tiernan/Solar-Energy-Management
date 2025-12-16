import subprocess
def renew_dhcp(interface="eth0"):
    try:
        # Run dhclient command
        result = subprocess.run(
            ["dhclient", "-v", interface],
            check=True,       # Raise exception if command fails
            capture_output=True,
            text=True
        )
        print("DHCP renew output:\n", result.stdout)
    except subprocess.CalledProcessError as e:
        print("Error running dhclient:\n", e.stderr)

# Example usage
renew_dhcp("eth0")
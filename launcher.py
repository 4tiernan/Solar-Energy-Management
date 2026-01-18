import subprocess
import sys
import time
from amber_api import AmberAPI  
from ha_api import HomeAssistantAPI
import PlantControl
from api_token_secrets import HA_URL, HA_TOKEN, AMBER_API_TOKEN, SITE_ID
from MPC import MPC

from multiprocessing import Queue


amber = AmberAPI(AMBER_API_TOKEN, SITE_ID, errors=True)

plant = PlantControl.Plant(HA_URL, HA_TOKEN, errors=True) 
ha = HomeAssistantAPI(
        base_url=HA_URL,
        token=HA_TOKEN,
        errors=True
    )

mpc = MPC(amber, plant, ha)


# Start Streamlit dashboard
streamlit_proc = subprocess.Popen([
    sys.executable,
    "-m",
    "streamlit",
    "run",
    "webserver.py",
    "--server.headless=true"
])

print("Streamlit dashboard started")

#q: Queue

try:
    # Your main loop
    output = mpc.run_optimisation()
    #q.put(output)
    while True:
        #print("Main loop running...")
        time.sleep(1)

except KeyboardInterrupt:
    print("Shutting down...")
    streamlit_proc.terminate()

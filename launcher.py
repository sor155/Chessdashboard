import subprocess
import os
import sys

# Get the directory where this launcher script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Define the paths to the two main scripts
updater_script = os.path.join(script_dir, 'update_sheets_tracker.py')
streamlit_app_script = os.path.join(script_dir, 'streamlit_app.py')

# Define the commands to run
# We use sys.executable to ensure we're using the same Python that ran this launcher
updater_command = [sys.executable, updater_script]
streamlit_command = [sys.executable, '-m', 'streamlit', 'run', streamlit_app_script]

# Use Popen to launch both scripts in new, separate console windows
print("Starting the updater script in a new window...")
subprocess.Popen(updater_command, creationflags=subprocess.CREATE_NEW_CONSOLE)

print("Starting the Streamlit dashboard in a new window...")
subprocess.Popen(streamlit_command, creationflags=subprocess.CREATE_NEW_CONSOLE)

print("\nBoth scripts have been launched in separate windows.")

#!/bin/bash
KLIPPER_PATH="${HOME}/klipper"
SYSTEMDDIR="/etc/systemd/system"
NUM_INSTALLS=0

# Step 1:  Verify Klipper has been installed
check_klipper()
{
	if [[ $NUM_INSTALLS == 0 ]]; then
		if [ "$(sudo systemctl list-units --full -all -t service --no-legend | grep -F "klipper.service")" ]; then
			echo "klipper.service found!"
		else
			echo "klipper.service not found, please install Klipper first of if using multiple instances use the -n flag"
			exit -1
		fi
	else
		for (( klip = 1; klip<=$NUM_INSTALLS; klip++)); do
			if [ "$(sudo systemctl list-units --full -all -t service --no-legend | grep -F "klipper-$klip.service")" ]; then
				echo "klipper-$klip.service found!"
			else
				echo "klipper-$klip.service NOT found, please ensure you've entered the correct number of klipper instances you're running!"
				exit -1
			fi			
		done	
	fi
}

# Step 2: link extension to Klipper
link_extension()
{
    echo "Linking extension to Klipper..."
    ln -sf "${SRCDIR}/z_calibration.py" "${KLIPPER_PATH}/klippy/extras/z_calibration.py"
}

# Step 3: Remove old dummy system service
remove_service()
{
    SERVICE_FILE="${SYSTEMDDIR}/z_calibration.service"
    if [ -f $SERVICE_FILE ]; then
        echo -e "Removing system service..."
        sudo service z_calibration stop
        sudo systemctl disable z_calibration.service
        sudo rm "$SERVICE_FILE"
    fi
    OLD_SERVICE_FILE="${SYSTEMDDIR}/klipper_z_calibration.service"
    if [ -f $OLD_SERVICE_FILE ]; then
        echo -e "Removing old system service..."
        sudo service klipper_z_calibration stop
        sudo systemctl disable klipper_z_calibration.service
        sudo rm "$OLD_SERVICE_FILE"
    fi
}

# Step 4: restarting Klipper
restart_klipper()
{
    if [[ $NUM_INSTALLS == 0 ]]; then
		sudo systemctl restart klipper && echo "Restarting klipper..."
    else
	    for (( klip = 1; klip<=$NUM_INSTALLS; klip++)); do
		    sudo systemctl restart klipper-$klip && echo "Restarting klipper-$klip.service"
	    done
    fi
}

# Helper functions
verify_ready()
{
    if [ "$EUID" -eq 0 ]; then
        echo "This script must not run as root"
        exit -1
    fi
    if [[ $NUM_INSTALLS == 0 ]]; then
	    echo "Defaulted to one klipper install, if more than one instance, use -n"
    else
	    echo "Number of Installs Selected: $NUM_INSTALLS"
    fi
}

# Force script to exit if an error occurs
set -e

# Find SRCDIR from the pathname of this script
SRCDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )"/ && pwd )"

# Parse command line arguments
while getopts "k:n:" arg; do
    case $arg in
        k) KLIPPER_PATH=$OPTARG;;
	    n) NUM_INSTALLS=$OPTARG;;
    esac
done

# Run steps
verify_ready
check_klipper
link_extension
remove_service
restart_klipper

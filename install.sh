#!/bin/bash
KLIPPER_PATH="${HOME}/klipper"
SYSTEMDDIR="/etc/systemd/system"

# Step 1:  Verify Klipper has been installed
check_klipper()
{
    if [ "$(sudo systemctl list-units --full -all -t service --no-legend | grep -F "klipper.service")" ]; then
        echo "Klipper service found!"
    else
        echo "Klipper service not found, please install Klipper first"
        exit -1
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
    echo "Restarting Klipper..."
    sudo systemctl restart klipper
}

# Helper functions
verify_ready()
{
    if [ "$EUID" -eq 0 ]; then
        echo "This script must not run as root"
        exit -1
    fi
}

# Force script to exit if an error occurs
set -e

# Find SRCDIR from the pathname of this script
SRCDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )"/ && pwd )"

# Parse command line arguments
while getopts "k:" arg; do
    case $arg in
        k) KLIPPER_PATH=$OPTARG;;
    esac
done

# Run steps
verify_ready
link_extension
remove_service
restart_klipper

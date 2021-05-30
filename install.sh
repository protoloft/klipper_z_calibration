#!/bin/bash
KLIPPER_PATH="${HOME}/klipper"

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

# Step 2: copy extension to Klipper
copy_extension()
{
    report_status "Copying extension to Klipper..."
    cp "${SRCDIR}/z_calibration.py" "${KLIPPER_PATH}/klippy/extras/z_calibration.py"
}

# Step 3: restarting Klipper
restart_klipper()
{
    report_status "Restarting Klipper..."
    sudo systemctl restart klipper
}

# Helper functions
report_status()
{
    echo -e "\n\n###### $1"
}

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
copy_extension
restart_klipper
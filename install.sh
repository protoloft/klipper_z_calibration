#!/bin/bash
# Install, update, or uninstall the z_calibration Klipper/Kalico plugin.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

SRCDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )"/ && pwd )"
KLIPPER_PATH="${HOME}/klipper"
MOONRAKER_CONFIG="${HOME}/printer_data/config/moonraker.conf"
MOONRAKER_FALLBACK="${HOME}/klipper_config/moonraker.conf"
MOONRAKER_CONFIG_CUSTOM=0
NUM_INSTALLS=0
NUM_INSTALLS_CUSTOM=0

# Force script to exit if an error occurs
set -e

set_install_paths()
{
    KALICO_PLUGIN_DIR="${KLIPPER_PATH}/klippy/plugins"
    KALICO_PLUGIN_FILE="${KALICO_PLUGIN_DIR}/z_calibration.py"
    KALICO_COMPAT_FILE="${KALICO_PLUGIN_DIR}/klipper_compat.py"
    KLIPPER_EXTRA_FILE="${KLIPPER_PATH}/klippy/extras/z_calibration.py"
    KLIPPER_COMPAT_FILE="${KLIPPER_PATH}/klippy/extras/klipper_compat.py"
}

is_repo_link()
{
    link_path="$1"
    target_path="$2"
    [ -L "$link_path" ] && [ "$(readlink "$link_path")" = "$target_path" ]
}

remove_repo_link()
{
    link_path="$1"
    target_path="$2"
    if is_repo_link "$link_path" "$target_path"; then
        rm -f "$link_path"
    fi
}

remove_file_if_present()
{
    file_path="$1"
    if [ -e "$file_path" ] || [ -L "$file_path" ]; then
        rm -f "$file_path"
    fi
}

validate_num_installs()
{
    if [ "$NUM_INSTALLS_CUSTOM" -eq 0 ]; then
        return
    fi
    if [[ ! "$NUM_INSTALLS" =~ ^[1-9][0-9]*$ ]]; then
        echo "Error: -n must be a positive integer"
        exit -1
    fi
}

# Step 1: Check for root user
verify_ready()
{
    validate_num_installs
    # check for root user
    if [ "$EUID" -eq 0 ]; then
        echo "This script must not run as root"
        exit -1
    fi
    # output used number of installs
    if [[ $NUM_INSTALLS == 0 ]]; then
        echo "Defaulted to one klipper install, if more than one instance, use -n"
    else
        echo "Number of Installs Selected: $NUM_INSTALLS"
    fi
}

# Step 2:  Verify Klipper has been installed
check_klipper()
{
    if [[ $NUM_INSTALLS == 0 ]]; then
        if [ "$(sudo systemctl list-units --full -all -t service --no-legend | grep -F "klipper.service")" ]; then
            echo "Klipper service found!"
        else
            echo "Klipper service not found, please install Klipper first"
            exit -1
        fi
    else
        for (( klip = 1; klip<=$NUM_INSTALLS; klip++ )); do
            if [ "$(sudo systemctl list-units --full -all -t service --no-legend | grep -F "klipper-$klip.service")" ]; then
                echo "klipper-$klip.service found!"
            else
                echo "klipper-$klip.service NOT found, please ensure you've entered the correct number of klipper instances you're running!"
                exit -1
            fi
        done
    fi
}

resolve_moonraker_config()
{
    if [ -f "$MOONRAKER_CONFIG" ]; then
        echo "Moonraker configuration found at ${MOONRAKER_CONFIG}"
        return
    fi
    if [ "$MOONRAKER_CONFIG_CUSTOM" -eq 0 ] \
       && [ -f "$MOONRAKER_FALLBACK" ]; then
        echo "${MOONRAKER_CONFIG} does not exist. Falling back to ${MOONRAKER_FALLBACK}"
        MOONRAKER_CONFIG="$MOONRAKER_FALLBACK"
        echo "Moonraker configuration found at ${MOONRAKER_CONFIG}"
        return
    fi
    if [ "$MOONRAKER_CONFIG_CUSTOM" -eq 0 ]; then
        echo "Error: Moonraker configuration not found: ${MOONRAKER_CONFIG} or ${MOONRAKER_FALLBACK}. Exiting.."
    else
        echo "Error: Moonraker configuration not found: ${MOONRAKER_CONFIG}. Exiting.."
    fi
    exit -1
}

# Step 3: Check folders
check_klipper_path()
{
    if [ ! -d "${KLIPPER_PATH}/klippy/extras/" ]; then
        echo "Error: Klipper not found in directory: ${KLIPPER_PATH}. Exiting.."
        exit -1
    fi
    echo "Klipper found at ${KLIPPER_PATH}"
}

check_requirements()
{
    check_klipper_path
    resolve_moonraker_config
}

# Step 4: Link extension to Klipper
link_kalico_extension()
{
    echo -n "Linking extension to Kalico plugins... "
    ln -sf "${SRCDIR}/z_calibration.py" "$KALICO_PLUGIN_FILE"
    remove_repo_link "$KLIPPER_EXTRA_FILE" "${SRCDIR}/z_calibration.py"
    remove_repo_link "$KLIPPER_COMPAT_FILE" "${SRCDIR}/klipper_compat.py"
    remove_repo_link "$KALICO_COMPAT_FILE" "${SRCDIR}/klipper_compat.py"
    remove_file_if_present "${KLIPPER_PATH}/klippy/extras/klipper_compat.pyc"
    remove_file_if_present "${KALICO_PLUGIN_DIR}/klipper_compat.pyc"
    echo "[OK]"
    echo "Kalico users must enable:"
    echo "  [danger_options]"
    echo "  allow_plugin_override: True"
}

link_klipper_extension()
{
    echo -n "Linking extension to Klipper extras... "
    ln -sf "${SRCDIR}/z_calibration.py" "$KLIPPER_EXTRA_FILE"
    remove_repo_link "$KLIPPER_COMPAT_FILE" "${SRCDIR}/klipper_compat.py"
    remove_file_if_present "${KLIPPER_PATH}/klippy/extras/klipper_compat.pyc"
    echo "[OK]"
}

link_extension()
{
    if [ -d "$KALICO_PLUGIN_DIR" ]; then
        link_kalico_extension
        return
    fi
    link_klipper_extension
}

# Step 5: Add updater to moonraker.conf
add_updater()
{
    echo -n "Adding update manager to moonraker.conf... "
    update_result=$(python3 \
        "${SRCDIR}/scripts/update_moonraker.py" \
        "$MOONRAKER_CONFIG" \
        "$SRCDIR")
    if [ "$update_result" = "changed" ]; then
        echo "[OK]"

        echo -n "Restarting Moonraker... "
        sudo systemctl restart moonraker
        echo "[OK]"
    else
        echo "[SKIPPED]"
    fi
}

# Step 6: Restarting Klipper
restart_klipper()
{
    if [[ $NUM_INSTALLS == 0 ]]; then
        echo -n "Restarting Klipper... "
        sudo systemctl restart klipper
        echo "[OK]"
    else
        for (( klip = 1; klip<=$NUM_INSTALLS; klip++)); do
            echo -n "Restarting Klipper-$klip... "
            sudo systemctl restart klipper-$klip
            echo "[OK]"
        done
    fi
}

uinstall()
{
    if is_repo_link "$KALICO_PLUGIN_FILE" "${SRCDIR}/z_calibration.py" \
       || is_repo_link "$KALICO_COMPAT_FILE" "${SRCDIR}/klipper_compat.py" \
       || is_repo_link "$KLIPPER_EXTRA_FILE" "${SRCDIR}/z_calibration.py" \
       || is_repo_link "$KLIPPER_COMPAT_FILE" "${SRCDIR}/klipper_compat.py"; then
        echo -n "Uninstalling z_calibration... "
        remove_repo_link \
            "$KALICO_PLUGIN_FILE" "${SRCDIR}/z_calibration.py"
        remove_repo_link \
            "$KALICO_COMPAT_FILE" "${SRCDIR}/klipper_compat.py"
        remove_file_if_present "${KALICO_PLUGIN_DIR}/z_calibration.pyc"
        remove_file_if_present "${KALICO_PLUGIN_DIR}/klipper_compat.pyc"
        remove_repo_link \
            "$KLIPPER_EXTRA_FILE" "${SRCDIR}/z_calibration.py"
        remove_repo_link \
            "$KLIPPER_COMPAT_FILE" "${SRCDIR}/klipper_compat.py"
        remove_file_if_present "${KLIPPER_PATH}/klippy/extras/z_calibration.pyc"
        remove_file_if_present "${KLIPPER_PATH}/klippy/extras/klipper_compat.pyc"
        echo "[OK]"
        echo "You can now remove the \"[update_manager z_calibration]\" section in your moonraker.conf and delete this directory."
        echo "You also need to remove the \"[z_calibration]\" section in your Klipper configuration..."
    else
        echo -n "z_calibration.py not found. Is it installed? "
        echo "[FAILED]"
    fi
}

usage()
{
    echo "Usage: $(basename $0) [-k <Klipper path>] [-m <Moonraker config file>] [-n <number klipper instances>] [-u]" 1>&2;
    exit 1;
}

# Command parsing
main()
{
    OPTIND=1
    UNINSTALL=""
    MOONRAKER_CONFIG_CUSTOM=0
    NUM_INSTALLS_CUSTOM=0
    while getopts ":k:m:n:uh" OPTION; do
        case "$OPTION" in
            k) KLIPPER_PATH="$OPTARG" ;;
            m) MOONRAKER_CONFIG="$OPTARG"
               MOONRAKER_CONFIG_CUSTOM=1 ;;
            n) NUM_INSTALLS="$OPTARG"
               NUM_INSTALLS_CUSTOM=1 ;;
            u) UNINSTALL=1 ;;
            h | ?) usage ;;
        esac
    done

    set_install_paths
    verify_ready
    check_klipper
    if [ -z "$UNINSTALL" ]; then
        check_requirements
        link_extension
        add_updater
    else
        check_klipper_path
        uinstall
    fi
    restart_klipper
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi

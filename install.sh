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
MOONRAKER_AVAILABLE=1
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
    local link_path="$1"
    local target_path="$2"
    [ -L "$link_path" ] && [ "$(readlink "$link_path")" = "$target_path" ]
}

remove_repo_link()
{
    local link_path="$1"
    local target_path="$2"
    if is_repo_link "$link_path" "$target_path"; then
        rm -f "$link_path"
    fi
}

remove_file_if_present()
{
    local file_path="$1"
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
        exit 1
    fi
}

# Step 1: Check for root user
verify_ready()
{
    validate_num_installs
    # check for root user
    if [ "$EUID" -eq 0 ]; then
        echo "This script must not run as root"
        exit 1
    fi
    # output used number of installs
    if [[ $NUM_INSTALLS == 0 ]]; then
        echo "Defaulted to one klipper install, if more than one instance, use -n"
    else
        echo "Number of Installs Selected: $NUM_INSTALLS"
    fi
}

service_exists()
{
    # Match the unit name exactly: a substring grep would accept an
    # unrelated unit such as "kalico-klipper.service" for "klipper.service".
    local unit="$1"
    sudo systemctl list-units --full --all -t service --no-legend --plain \
        | awk '{print $1}' | grep -qx "$unit"
}

# Step 2:  Verify Klipper has been installed
check_klipper()
{
    if [[ $NUM_INSTALLS == 0 ]]; then
        if service_exists "klipper.service"; then
            echo "Klipper service found!"
        else
            echo "Klipper service not found, please install Klipper first"
            exit 1
        fi
    else
        local klip
        for (( klip = 1; klip<=$NUM_INSTALLS; klip++ )); do
            if service_exists "klipper-$klip.service"; then
                echo "klipper-$klip.service found!"
            else
                echo "klipper-$klip.service NOT found, please ensure you've entered the correct number of klipper instances you're running!"
                exit 1
            fi
        done
    fi
}

# Moonraker is optional: it manages updates, it does not run the plugin.
# A missing configuration at the default locations only skips the update
# manager step. A path given with -m is an explicit request and must exist,
# otherwise the caller would silently not get what was asked for.
resolve_moonraker_config()
{
    if [ -f "$MOONRAKER_CONFIG" ]; then
        echo "Moonraker configuration found at ${MOONRAKER_CONFIG}"
        return 0
    fi
    if [ "$MOONRAKER_CONFIG_CUSTOM" -eq 1 ]; then
        echo "Error: Moonraker configuration not found: ${MOONRAKER_CONFIG}. Exiting.."
        exit 1
    fi
    if [ -f "$MOONRAKER_FALLBACK" ]; then
        echo "${MOONRAKER_CONFIG} does not exist. Falling back to ${MOONRAKER_FALLBACK}"
        MOONRAKER_CONFIG="$MOONRAKER_FALLBACK"
        echo "Moonraker configuration found at ${MOONRAKER_CONFIG}"
        return 0
    fi
    echo "No Moonraker configuration found at ${MOONRAKER_CONFIG} or ${MOONRAKER_FALLBACK}."
    echo "Skipping the update manager. Use -m <path> if Moonraker is installed elsewhere."
    return 1
}

# Step 3: Check folders
check_klipper_path()
{
    if [ ! -d "${KLIPPER_PATH}/klippy/extras/" ]; then
        echo "Error: Klipper not found in directory: ${KLIPPER_PATH}. Exiting.."
        exit 1
    fi
    echo "Klipper found at ${KLIPPER_PATH}"
}

check_requirements()
{
    check_klipper_path
    # Declared separately from the "if": under "set -e" a failing call in a
    # condition is fine, but a bare call would end the script.
    if resolve_moonraker_config; then
        MOONRAKER_AVAILABLE=1
    else
        MOONRAKER_AVAILABLE=0
    fi
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
    # Declared separately: "local x=$(cmd)" would report the exit status of
    # "local" and hide a failing command substitution from "set -e".
    local update_result
    update_result=$(python3 \
        "${SRCDIR}/scripts/update_moonraker.py" \
        "$MOONRAKER_CONFIG" \
        "$SRCDIR")
    if [ "$update_result" = "changed" ]; then
        echo "[OK]"
        # Multi-instance setups often have no plain "moonraker" unit, and
        # a failed restart must not abort an otherwise finished install.
        restart_service moonraker
    else
        echo "[SKIPPED]"
    fi
}

restart_service()
{
    local unit="$1"
    echo -n "Restarting ${unit}... "
    if sudo systemctl restart "$unit"; then
        echo "[OK]"
    else
        echo "[FAILED] - please restart ${unit} manually"
    fi
}

# Step 6: Restarting Klipper
restart_klipper()
{
    if [[ $NUM_INSTALLS == 0 ]]; then
        restart_service klipper
    else
        local klip
        for (( klip = 1; klip<=$NUM_INSTALLS; klip++)); do
            restart_service "klipper-$klip"
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
        return 0
    fi
    echo -n "z_calibration.py not found, nothing to uninstall. "
    echo "[SKIPPED]"
    warn_foreign_leftovers
    # Not an error: rerunning -u has to stay idempotent. The caller uses the
    # status only to decide whether Klipper has to be restarted.
    return 1
}

warn_foreign_leftovers()
{
    # A link created from a moved or renamed checkout does not resolve to
    # this checkout any more, so uninstall leaves it alone by design. Say
    # so instead of reporting a clean tree while a stale plugin file keeps
    # loading into Klipper.
    local file_path
    for file_path in "$KALICO_PLUGIN_FILE" "$KALICO_COMPAT_FILE" \
                     "$KLIPPER_EXTRA_FILE" "$KLIPPER_COMPAT_FILE"; do
        if [ -e "$file_path" ] || [ -L "$file_path" ]; then
            echo "Warning: $file_path exists but is not owned by this checkout - remove it manually if it is stale."
        fi
    done
}

print_usage()
{
    echo "Usage: $(basename "$0") [-k <Klipper path>] [-m <Moonraker config file>] [-n <number klipper instances>] [-u] [-h]"
}

usage()
{
    print_usage 1>&2
    exit 1
}

# Command parsing
main()
{
    OPTIND=1
    UNINSTALL=""
    MOONRAKER_CONFIG_CUSTOM=0
    MOONRAKER_AVAILABLE=1
    NUM_INSTALLS=0
    NUM_INSTALLS_CUSTOM=0
    local OPTION
    while getopts ":k:m:n:uh" OPTION; do
        case "$OPTION" in
            k) KLIPPER_PATH="$OPTARG" ;;
            m) MOONRAKER_CONFIG="$OPTARG"
               MOONRAKER_CONFIG_CUSTOM=1 ;;
            n) NUM_INSTALLS="$OPTARG"
               NUM_INSTALLS_CUSTOM=1 ;;
            u) UNINSTALL=1 ;;
            h) print_usage
               exit 0 ;;
            ?) usage ;;
        esac
    done

    set_install_paths
    verify_ready
    if [ -z "$UNINSTALL" ]; then
        check_klipper
        check_requirements
        link_extension
        if [ "$MOONRAKER_AVAILABLE" -eq 1 ]; then
            add_updater
        fi
    else
        # Uninstall cleans up symlinks; it must work without a reachable
        # Klipper service, so the service check is skipped here and the
        # restart below tolerates a missing unit.
        check_klipper_path
        # Nothing removed means nothing changed for Klipper, so there is no
        # reason to restart it. The "if" also keeps "set -e" from ending the
        # script on the non-zero status.
        if ! uinstall; then
            return 0
        fi
    fi
    restart_klipper
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi

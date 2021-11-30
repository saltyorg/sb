#!/bin/bash
#########################################################################
# Title:         Saltbox: SB Script                                     #
# Author(s):     desimaniac, chazlarson, salty                          #
# URL:           https://github.com/saltyorg/sb                         #
# --                                                                    #
#########################################################################
#                   GNU General Public License v3.0                     #
#########################################################################

################################
# Privilege Escalation
################################

# Restart script in SUDO
# https://unix.stackexchange.com/a/28793

if [ $EUID != 0 ]; then
    sudo "$0" "$@"
    exit $?
fi

################################
# Scripts
################################

source /srv/git/sb/yaml.sh
create_variables /srv/git/saltbox/accounts.yml

################################
# Variables
################################

#Ansible
ANSIBLE_PLAYBOOK_BINARY_PATH="/usr/local/bin/ansible-playbook"

# Saltbox
SALTBOX_REPO_PATH="/srv/git/saltbox"
SALTBOX_PLAYBOOK_PATH="$SALTBOX_REPO_PATH/saltbox.yml"
SALTBOX_LOGFILE_PATH="$SALTBOX_REPO_PATH/saltbox.log"

# Community
COMMUNITY_REPO_PATH="/opt/community"
COMMUNITY_PLAYBOOK_PATH="$COMMUNITY_REPO_PATH/community.yml"
COMMUNITY_LOGFILE_PATH="$COMMUNITY_REPO_PATH/community.log"

# Sandbox
SANDBOX_REPO_PATH="/opt/sandbox"
SANDBOX_PLAYBOOK_PATH="$SANDBOX_REPO_PATH/sandbox.yml"
SANDBOX_LOGFILE_PATH="$SANDBOX_REPO_PATH/sandbox.log"

# SB
SB_REPO_PATH="/srv/git/sb"

################################
# Functions
################################

git_fetch_and_reset () {

    git fetch --quiet >/dev/null
    git clean --quiet -df >/dev/null
    git reset --quiet --hard "@{u}" >/dev/null
    git checkout --quiet master >/dev/null
    git clean --quiet -df >/dev/null
    git reset --quiet --hard "@{u}" >/dev/null
    git submodule update --init --recursive
    chmod 664 "${SALTBOX_REPO_PATH}/ansible.cfg"
    # shellcheck disable=SC2154
    chown -R "${user_name}":"${user_name}" "${SALTBOX_REPO_PATH}"
}

git_fetch_and_reset_community () {

    git fetch --quiet >/dev/null
    git clean --quiet -df >/dev/null
    git reset --quiet --hard "@{u}" >/dev/null
    git checkout --quiet master >/dev/null
    git clean --quiet -df >/dev/null
    git reset --quiet --hard "@{u}" >/dev/null
    git submodule update --init --recursive
    chmod 664 "${COMMUNITY_REPO_PATH}/ansible.cfg"
    chown -R "${user_name}":"${user_name}" "${COMMUNITY_REPO_PATH}"
}

git_fetch_and_reset_sandbox () {

    git fetch --quiet >/dev/null
    git clean --quiet -df >/dev/null
    git reset --quiet --hard "@{u}" >/dev/null
    git checkout --quiet master >/dev/null
    git clean --quiet -df >/dev/null
    git reset --quiet --hard "@{u}" >/dev/null
    git submodule update --init --recursive
    chmod 664 "${SANDBOX_REPO_PATH}/ansible.cfg"
    chown -R "${user_name}":"${user_name}" "${SANDBOX_REPO_PATH}"
}

git_fetch_and_reset_sb () {

    git fetch --quiet >/dev/null
    git clean --quiet -df >/dev/null
    git reset --quiet --hard "@{u}" >/dev/null
    git checkout --quiet master >/dev/null
    git clean --quiet -df >/dev/null
    git reset --quiet --hard "@{u}" >/dev/null
    git submodule update --init --recursive
    chmod 775 "${SB_REPO_PATH}/sb.sh"
}

run_playbook_sb () {

    local arguments=$*

    echo "" > "${SALTBOX_LOGFILE_PATH}"

    cd "${SALTBOX_REPO_PATH}" || exit

    # shellcheck disable=SC2086
    "${ANSIBLE_PLAYBOOK_BINARY_PATH}" \
        "${SALTBOX_PLAYBOOK_PATH}" \
        --become \
        ${arguments}

    cd - >/dev/null || exit

}

run_playbook_cm () {

    local arguments=$*

    echo "" > "${COMMUNITY_LOGFILE_PATH}"

    cd "${COMMUNITY_REPO_PATH}" || exit

    # shellcheck disable=SC2086
    "${ANSIBLE_PLAYBOOK_BINARY_PATH}" \
        "${COMMUNITY_PLAYBOOK_PATH}" \
        --become \
        ${arguments}

    cd - >/dev/null || exit

}

run_playbook_sandbox () {

    local arguments=$*

    echo "" > "${SANDBOX_LOGFILE_PATH}"

    cd "${SANDBOX_REPO_PATH}" || exit

    # shellcheck disable=SC2086
    "${ANSIBLE_PLAYBOOK_BINARY_PATH}" \
        "${SANDBOX_PLAYBOOK_PATH}" \
        --become \
        ${arguments}

    cd - >/dev/null || exit

}

install () {

    local arg=("$@")
    echo "${arg[*]}"

    # Remove space after comma
    # shellcheck disable=SC2128,SC2001
    arg_clean=$(sed -e 's/, /,/g' <<< "$arg")

    # Split tags from extra arguments
    # https://stackoverflow.com/a/10520842
    re="^(\S+)\s+(-.*)?$"
    if [[ "$arg_clean" =~ $re ]]; then
        tags_arg="${BASH_REMATCH[1]}"
        extra_arg="${BASH_REMATCH[2]}"
    else
        tags_arg="$arg_clean"
    fi

    # Save tags into 'tags' array
    # shellcheck disable=SC2206
    tags_tmp=(${tags_arg//,/ })

    # Remove duplicate entries from array
    # https://stackoverflow.com/a/31736999
    readarray -t tags < <(printf '%s\n' "${tags_tmp[@]}" | awk '!x[$0]++')

    # Build SB/CM tag arrays
    local tags_sb
    local tags_cm
    local tags_sandbox

    for i in "${!tags[@]}"
    do
        if [[ ${tags[i]} == cm-* ]]; then
            tags_cm="${tags_cm}${tags_cm:+,}${tags[i]##cm-}"

        elif [[ ${tags[i]} == sandbox-* ]]; then
            tags_sandbox="${tags_sandbox}${tags_sandbox:+,}${tags[i]##sandbox-}"

        else
            tags_sb="${tags_sb}${tags_sb:+,}${tags[i]}"

        fi
    done

    # Saltbox Ansible Playbook
    if [[ -n "$tags_sb" ]]; then

        # Build arguments
        local arguments_sb="--tags $tags_sb"

        if [[ -n "$extra_arg" ]]; then
            arguments_sb="${arguments_sb} ${extra_arg}"
        fi

        # Run playbook
        echo ""
        echo "Running Saltbox Tags: ${tags_sb//,/,  }"
        echo ""
        run_playbook_sb "$arguments_sb"
        echo ""

    fi

    # Community Ansible Playbook
    if [[ -n "$tags_cm" ]]; then

        # Build arguments
        local arguments_cm="--tags $tags_cm"

        if [[ -n "$extra_arg" ]]; then
            arguments_cm="${arguments_cm} ${extra_arg}"
        fi

        # Run playbook
        echo "========================="
        echo ""
        echo "Running Community Tags: ${tags_cm//,/,  }"
        echo ""
        run_playbook_cm "$arguments_cm"
        echo ""
    fi

    # Sandbox Ansible Playbook
    if [[ -n "$tags_sandbox" ]]; then

        # Build arguments
        local arguments_sandbox="--tags $tags_sandbox"

        if [[ -n "$extra_arg" ]]; then
            arguments_sandbox="${arguments_sandbox} ${extra_arg}"
        fi

        # Run playbook
        echo "========================="
        echo ""
        echo "Running Sandbox Tags: ${tags_sandbox//,/,  }"
        echo ""
        run_playbook_sandbox "$arguments_sandbox"
        echo ""
    fi

}

update () {

    if [[ -d "${SALTBOX_REPO_PATH}" ]]
    then
        echo -e "Updating Saltbox...\n"

        cd "${SALTBOX_REPO_PATH}" || exit

        git_fetch_and_reset

        run_playbook_sb "--tags settings" && echo -e '\n'

        echo -e "Update Completed."
    else
        echo -e "Saltbox folder not present."
    fi

}

cm-update () {

    if [[ -d "${COMMUNITY_REPO_PATH}" ]]
    then
        echo -e "Updating Community...\n"

        cd "${COMMUNITY_REPO_PATH}" || exit

        git_fetch_and_reset_community

        run_playbook_cm "--tags settings" && echo -e '\n'

        echo -e "Update Completed."
    fi

}

sandbox-update () {

    if [[ -d "${SANDBOX_REPO_PATH}" ]]
    then
        echo -e "Updating Sandbox...\n"

        cd "${SANDBOX_REPO_PATH}" || exit

        git_fetch_and_reset_sandbox

        run_playbook_sandbox "--tags settings" && echo -e '\n'

        echo -e "Update Completed."
    fi

}

sb-update () {

    echo -e "Updating sb...\n"

    cd "${SB_REPO_PATH}" || exit

    git_fetch_and_reset_sb

    echo -e "Update Completed."

}

sb-list ()  {

    if [[ -d "${SALTBOX_REPO_PATH}" ]]
    then
        echo -e "Saltbox tags:\n"

        cd "${SALTBOX_REPO_PATH}" || exit

        "${ANSIBLE_PLAYBOOK_BINARY_PATH}" \
            "${SALTBOX_PLAYBOOK_PATH}" \
            --become \
            --list-tags --skip-tags "always" 2>&1 | grep "TASK TAGS" | cut -d":" -f2 | awk '{sub(/\[/, "")sub(/\]/, "")}1' | cut -c2-

        echo -e "\n"

        cd - >/dev/null || exit
    else
        echo -e "Saltbox folder not present.\n"
    fi

}

cm-list () {

    if [[ -d "${COMMUNITY_REPO_PATH}" ]]
    then
        echo -e "Community tags (prepend cm-):\n"

        cd "${COMMUNITY_REPO_PATH}" || exit
        "${ANSIBLE_PLAYBOOK_BINARY_PATH}" \
            "${COMMUNITY_PLAYBOOK_PATH}" \
            --become \
            --list-tags --skip-tags "always,sanity_check" 2>&1 | grep "TASK TAGS" | cut -d":" -f2 | awk '{sub(/\[/, "")sub(/\]/, "")}1' | cut -c2-

        echo -e "\n"

        cd - >/dev/null || exit
    fi

}

sandbox-list () {

    if [[ -d "${SANDBOX_REPO_PATH}" ]]
    then
        echo -e "Sandbox tags (prepend sandbox-):\n"

        cd "${SANDBOX_REPO_PATH}" || exit
        "${ANSIBLE_PLAYBOOK_BINARY_PATH}" \
            "${SANDBOX_PLAYBOOK_PATH}" \
            --become \
            --list-tags --skip-tags "always,sanity_check" 2>&1 | grep "TASK TAGS" | cut -d":" -f2 | awk '{sub(/\[/, "")sub(/\]/, "")}1' | cut -c2-

        echo -e "\n"

        cd - >/dev/null || exit
    fi

}

list () {
    sb-list
    cm-list
    sandbox-list
}

usage () {
    echo "Usage:"
    echo "    sb update              Update Saltbox."
    echo "    sb list                List Saltbox packages."
    echo "    sb install <package>   Install <package>."
}

################################
# Update check
################################

cd "${SB_REPO_PATH}" || exit

git fetch
HEADHASH=$(git rev-parse HEAD)
UPSTREAMHASH=$(git rev-parse "master@{upstream}")

if [ "$HEADHASH" != "$UPSTREAMHASH" ]
then
 echo -e Not up to date with origin. Updating.
 sb-update
 echo -e Relaunching with previous arguments.
 sudo "$0" "$@"
 exit 0
fi

################################
# Argument Parser
################################

# https://sookocheff.com/post/bash/parsing-bash-script-arguments-with-shopts/

roles=""  # Default to empty role
#target=""  # Default to empty target

# Parse options
while getopts ":h" opt; do
  case ${opt} in
    h)
        usage
        exit 0
        ;;
   \?)
        echo "Invalid Option: -$OPTARG" 1>&2
        echo ""
        usage
        exit 1
     ;;
  esac
done
shift $((OPTIND -1))

# Parse commands
subcommand=$1; shift  # Remove 'sb' from the argument list
case "$subcommand" in

  # Parse options to the various sub commands
    list)
        list
        ;;
    update)
        update
        cm-update
        sandbox-update
        ;;
    install)
        roles=${*}
        install "${roles}"
        ;;
    "") echo "A command is required."
        echo ""
        usage
        exit 1
        ;;
    *)
        echo "Invalid Command: $subcommand"
        echo ""
        usage
        exit 1
        ;;
esac

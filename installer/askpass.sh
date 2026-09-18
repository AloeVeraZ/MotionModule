#!/bin/sh
# sudo runs this when a command in a dashboard update needs the Pi user's
# password: the update's service names it in SUDO_ASKPASS. The password the
# dashboard was given for that update is held by the root helper, which gives
# it only to processes inside the update.
exec sudo -n /usr/local/sbin/motionmodule-update password

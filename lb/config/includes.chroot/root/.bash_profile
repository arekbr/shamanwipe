# ShamanWipe: start the program on the local console (tty1) and on the serial console (ttyS0).
# The menu runs on both consoles; the program's lock covers only disk operations (the other console then shows
# a progress view, and in AUTO mode any key there aborts the countdown). AUTO prefers tty1.
# LANG comes from the boot menu entry (locales=); C.UTF-8 keeps UTF-8 output when it is missing.
export LANG="${LANG:-C.UTF-8}"
case "$(tty)" in
  /dev/tty1|/dev/ttyS0)
    if [ -z "$SW_START_DONE" ]; then
      export SW_START_DONE=1
      /usr/local/sbin/shamanwipe start
      echo
      # Language in the same order as the program: SW_LANG, then sw.lang= on the kernel command line, then LANG
      sw_lang="${SW_LANG:-$(tr ' ' '\n' < /proc/cmdline | sed -n 's/^sw\.lang=//p' | head -1)}"
      case "${sw_lang:-${LANG:0:2}}" in
        pl*) echo "Program zakończony. Powłoka root — 'shamanwipe' uruchamia go ponownie, 'poweroff' wyłącza komputer." ;;
        *) echo "Program finished. Root shell — 'shamanwipe' starts it again, 'poweroff' shuts the computer down." ;;
      esac
    fi
    ;;
esac
[ -f ~/.bashrc ] && . ~/.bashrc

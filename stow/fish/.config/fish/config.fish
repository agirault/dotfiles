if status is-interactive
    # Run shared login script (POSIX, shared with bash)
    # Executed as subprocess - env changes won't persist, only side-effects
    set -l login_script "$HOME/.config/env/login.sh"
    test -r "$login_script"; and bash "$login_script"
end

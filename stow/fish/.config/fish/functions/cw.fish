function cw --description "Create or attach to a tmux workspace"
    set -l session_name "work"
    set -l win_name $argv[1]

    # --- Helper: create a new workspace window ---
    function __cw_create_window --argument-names sess name dir
        tmux new-window -t $sess -n $name -c $dir
        tmux split-window -h -t $sess:$name -c $dir
        tmux select-pane -t $sess:$name.0
    end

    # --- Helper: attach via a grouped session so each terminal gets its own view ---
    function __cw_attach --argument-names sess win
        # Create a temporary grouped session linked to the main one
        # Each grouped session can independently display a different window
        set -l view "view-"(random)
        # destroy-unattached cleans up the view on detach, SSH drop, or terminal close
        # Must attach in the same command (-d omitted) so the session isn't destroyed
        # before a client connects
        if test -n "$win"
            tmux new-session -t $sess -s $view \; set-option destroy-unattached on \; select-window -t $win
        else
            tmux new-session -t $sess -s $view \; set-option destroy-unattached on
        end
    end

    # --- Ensure main session exists ---
    function __cw_ensure_session --argument-names sess name dir
        if not tmux has-session -t $sess 2>/dev/null
            tmux new-session -d -s $sess -n $name -c $dir
            tmux split-window -h -t $sess:$name -c $dir
            tmux select-pane -t $sess:$name.0
            return 0
        end
        return 1
    end

    # --- Cleanup helper ---
    function __cw_cleanup
        functions -e __cw_create_window __cw_attach __cw_ensure_session __cw_cleanup
    end

    # --- If a name was given: create or switch to that window ---
    if test -n "$win_name"
        __cw_ensure_session $session_name $win_name (pwd)
        or begin
            # Session exists — create window if needed
            if not tmux list-windows -t $session_name -F '#{window_name}' | grep -qx "$win_name"
                __cw_create_window $session_name $win_name (pwd)
            end
        end

        if not set -q TMUX
            __cw_attach $session_name $win_name
        else
            tmux select-window -t $session_name:$win_name
        end
        __cw_cleanup
        return
    end

    # --- No name given: show picker ---
    set -l options
    if tmux has-session -t $session_name 2>/dev/null
        set options (tmux list-windows -t $session_name -F '#{window_name}')
    end

    set -l new_label "+ new workspace"
    set options $options $new_label

    set -l pick (printf '%s\n' $options | fzf --height=~15 --reverse --prompt="workspace: ")

    if test -z "$pick"
        __cw_cleanup
        return 1
    end

    if test "$pick" = "$new_label"
        set -l default_name (basename (pwd))
        if not read -P "Workspace ID (defaults to: $default_name): " pick
            __cw_cleanup
            return 1
        end
        if test -z "$pick"
            set pick $default_name
        end

        # Ensure unique name — loop until valid
        while tmux has-session -t $session_name 2>/dev/null
            set -l existing (tmux list-windows -t $session_name -F '#{window_name}')
            if not contains $pick $existing
                break
            end
            echo "'$pick' already exists. Pick another name."
            if not read -P "Workspace ID (defaults to: $default_name): " pick
                __cw_cleanup
                return 1
            end
            if test -z "$pick"
                set pick $default_name
            end
        end

        __cw_ensure_session $session_name $pick (pwd)
        or __cw_create_window $session_name $pick (pwd)
    end

    if not set -q TMUX
        __cw_attach $session_name $pick
    else
        tmux select-window -t $session_name:$pick
    end
    __cw_cleanup
end

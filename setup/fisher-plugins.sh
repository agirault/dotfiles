#!/usr/bin/env bash
set -euo pipefail

echo "==> Setting up fish shell..."

# Make fish default shell
fish_path=$(which fish)
if ! grep -q "$fish_path" /etc/shells; then
    echo "$fish_path" | sudo tee -a /etc/shells
fi
if [[ "$SHELL" != "$fish_path" ]]; then
    sudo chsh -s "$fish_path" "$USER"
fi

# Install Nerd Font (FiraCode)
if ! find /usr/share/fonts -name "*FiraCodeNerdFont*" 2>/dev/null | grep -q "."; then
    echo "    Installing FiraCode Nerd Font..."
    font_url="https://github.com/ryanoasis/nerd-fonts/releases/download/v3.4.0/FiraCode.zip"
    sudo wget -q -O /tmp/FiraCode.zip "$font_url"
    sudo unzip -o /tmp/FiraCode.zip -d "/usr/share/fonts/truetype/FiraCode" >/dev/null
    sudo rm -f /tmp/FiraCode.zip
    fc-cache -f >/dev/null 2>&1
fi

# Install Fisher + Tide
if ! fish -c "fisher list 2>/dev/null" | grep -q "tide"; then
    echo "    Installing Fisher and Tide prompt..."
    fish -c "curl -sL https://raw.githubusercontent.com/jorgebucaran/fisher/main/functions/fisher.fish | source \
        && fisher install jorgebucaran/fisher IlanCosman/tide@v6 \
        && tide configure --auto \
            --style=Classic \
            --prompt_colors='True color' \
            --classic_prompt_color=Light \
            --show_time='12-hour format' \
            --classic_prompt_separators=Angled \
            --powerline_prompt_heads=Sharp \
            --powerline_prompt_tails=Slanted \
            --powerline_prompt_style='Two lines, character and frame' \
            --prompt_connection=Solid \
            --powerline_right_prompt_frame=No \
            --prompt_connection_andor_frame_color=Light \
            --prompt_spacing=Sparse \
            --icons='Many icons' \
            --transient=No"
else
    echo "    Fisher and Tide already installed."
fi

echo "==> Fish shell configured."

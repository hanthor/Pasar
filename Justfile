APP_ID := "dev.hanthor.Pasar"
MANIFEST := APP_ID + ".json"
BUILD_DIR := ".flatpak-build"
REPO_DIR := ".flatpak-repo"
STATE_DIR := ".flatpak-state"

# Build the Flatpak and install it into the user Flatpak installation
default: dev

# Build the Flatpak
build:
    flatpak run org.flatpak.Builder \
        --force-clean \
        --state-dir={{STATE_DIR}} \
        --repo={{REPO_DIR}} \
        {{BUILD_DIR}} \
        {{MANIFEST}}

# Install the just-built Flatpak (adds/updates the local repo and installs)
install: build
    flatpak --user remote-add --no-gpg-verify --if-not-exists pasar-local {{REPO_DIR}}
    flatpak --user install --or-update --noninteractive pasar-local {{APP_ID}}

# Run the installed Flatpak
run:
    flatpak run {{APP_ID}}

run-direct:
    ./run.sh

# Build, install, and immediately run
dev: install run

# Uninstall the app and remove the local remote
uninstall:
    flatpak --user uninstall --noninteractive {{APP_ID}} || true
    flatpak --user remote-delete pasar-local || true

# Clean all build artefacts
clean:
    rm -rf {{BUILD_DIR}} {{REPO_DIR}} {{STATE_DIR}}

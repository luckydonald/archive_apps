#####################
### User Settings ###
#####################

# Personal values (NAS, share, folder, tool paths) live in the hidden, git-ignored
# `.env.Makefile` next to this Makefile. Copy `.env.Makefile.example` to get started.
#
# Use another file with: make ENV_FILE=/path/to/other-env-file
SCRIPT_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
ENV_FILE ?= $(SCRIPT_DIR)/.env.Makefile

# This is the include of that file:
-include $(ENV_FILE)

# Mount & Path (required, set in the env file)
#   SERVER  name of the NAS
#   SHARE   name of the shared folder
#   FOLDER  path inside the share where the zips go (not `PATH`, that would clobber the shell's $PATH)
ifeq ($(and $(SERVER),$(SHARE),$(FOLDER)),)
$(error SERVER, SHARE and FOLDER must be set in $(ENV_FILE) (copy .env.Makefile.example there and fill it in))
endif

# Interpreter & Environment (optional overrides, set in the env file)
# The tool is the `archive_apps` package, run as a module from this directory.
PYTHON ?= $(SCRIPT_DIR)/.venv/bin/python
UV ?= uv

##########################
### internal constants ###
##########################

.PHONY: archive mount mount-mount mount-wait verify-zips verify-app verify-new verify-changed verify-abort
.DEFAULT_GOAL := archive

RUN := cd "$(SCRIPT_DIR)" && "$(UV)" run "$(PYTHON)" -m archive_apps
VOLUME := /Volumes/$(SHARE)
DESTINATION := $(VOLUME)/$(FOLDER)

# sh/make has weird $PATH setup, use direct paths:
OPEN := /usr/bin/open
SLEEP := /bin/sleep
MOUNT := /sbin/mount
GREP := /usr/bin/grep


###############
### helpers ###
###############


# `actual-mount-root` will return the actual mount path of the (sub-)dir given.
# Usage: $(call is-mounted,/Volumes/Drive/some/weird/subpath)
# Like bash `${1}`, here `$(1)` is the path to check.
# Will return the actual mount path from the last column of `df -P "$(1)"`
#
#
# Example outputs for reference:
#
# # ➜ df -P "/Volumes/Shed/Apps"
# # Filesystem                                 512-blocks       Used Available Capacity  Mounted on
# # //littlepip@GoldenOak._smb._tcp.local/Shed 8589934592 8493480736  96453856    99%    /Volumes/Shed
#
# # ➜ df -P "/Volumes/untitled folder"
# # Filesystem   512-blocks      Used Available Capacity  Mounted on
# # /dev/disk3s1  965595304 884031696  32463880    97%    /System/Volumes/Data
#
# # ➜ df -P "/Volumes/typo"
# # df: /Volumes/typo: No such file or directory
# (Exit status ≠0)
#
actual-mount-root = $(shell \
  df -P "$(1)" 2>/dev/null | \
  tail -n 1 | \
  awk '{print $$NF}' \
)

define APP_REQUIRED_ERROR
APP is required.

Usage:
  make verify-app APP=<app>

<app> must be one of:
  XCode
  XCode.app
  /Applications/Xcode.app
  Xcode.app@15.4.zip
  $(SHARE)/Xcode.app
endef


####################
### calculations ###
####################

# `mounted`: if `$(VOLUME)`'s path is a mounted drive, and specifically it's root folder, this variable `mounted` is set to` $(VOLUME)`'s contents, otherwise it remains empty.
# You can therefore check for that mount's existence (basically `if (mounted != '')`) with Makefile's `ifneq($(mounted),)`.
# The used `$(filter a,b)` is basically `a if a == b else ''`.
mounted := $(filter $(VOLUME),$(call is-mounted,$(VOLUME)))

####################
### make targets ###
####################

mount-mount:
ifeq ($(mounted),)
	@echo "Don't need to mount $(VOLUME)."
else
	@echo "Mounting $(VOLUME)…"
	$(OPEN) "smb://$(SERVER)/$(SHARE)"
endif

mount-wait:
	@echo "Waiting for $(VOLUME) to be ready..."
	@i=0; \
	while ! $(MOUNT) | $(GREP) -Fq "on $(VOLUME) "; do \
		if [ "$$i" -ge 30 ]; then \
			echo "Timed out waiting for $(VOLUME)" >&2; \
			exit 1; \
		fi; \
		$(SLEEP) 1; \
		i=$$((i + 1)); \
	done
	@echo "$(VOLUME) is mounted."

mount: mount-mount mount-wait

archive: mount
	@until test -d "$(DESTINATION)"; do \
		echo "Waiting for Shed to mount..."; \
		sleep 1; \
	done
	$(RUN) "$(DESTINATION)"

verify-app: mount
ifndef APP
	$(error $(APP_REQUIRED_ERROR))
endif
	$(RUN) \
		--verify-zip="$(APP)" \
		"$(DESTINATION)"

verify-zips: mount
	$(RUN) --verify-zips "$(DESTINATION)"

verify-new: mount
	$(RUN) --verify-new "$(DESTINATION)"

verify-changed: mount
	$(RUN) --verify-changed "$(DESTINATION)"

verify-abort: mount
	$(RUN) --verify-abort "$(DESTINATION)"


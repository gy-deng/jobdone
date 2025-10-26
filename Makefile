# All comments in this Makefile are in English.

APP_NAME := jobdone
VENV_DIR := .venv
VENV_BIN := $(VENV_DIR)/bin

.PHONY: venv dev-install dev build install clean

venv:
	python3 -m venv $(VENV_DIR)
	$(VENV_BIN)/pip install -U pip wheel setuptools

dev-install: venv
	$(VENV_BIN)/pip install -e .

dev: venv
	$(VENV_BIN)/python -m jobdone.cli --version || true

build: venv
	$(VENV_BIN)/pip install -e .
	$(VENV_BIN)/pip install pyinstaller pyyaml
	$(VENV_BIN)/pyinstaller --onefile -n $(APP_NAME) --hidden-import=yaml src/jobdone/cli.py

install: build
	@if [ "$$(id -u)" = "0" ]; then \
	  DEST_DIR=/usr/local/bin; \
	else \
	  DEST_DIR="$$HOME/.local/bin"; \
	fi; \
	mkdir -p $$DEST_DIR; \
	ln -sf $(CURDIR)/dist/$(APP_NAME) $$DEST_DIR/$(APP_NAME); \
	if [ "$$(id -u)" = "0" ]; then \
	  echo "Installed $(CURDIR)/dist/$(APP_NAME) -> $$DEST_DIR/$(APP_NAME). Ensure \"/usr/local/bin\" is in PATH."; \
	else \
	  echo "Installed $(CURDIR)/dist/$(APP_NAME) -> $$DEST_DIR/$(APP_NAME). Ensure \"$$HOME/.local/bin\" is in PATH."; \
	fi

clean:
	rm -rf build dist *.spec $(VENV_DIR)
# All comments in this Makefile are in English.

APP_NAME := jobdone
VENV_DIR := .venv
VENV_BIN := $(VENV_DIR)/bin

.PHONY: venv install dev build link clean

venv:
	python3 -m venv $(VENV_DIR)
	$(VENV_BIN)/pip install -U pip wheel setuptools

install: venv
	$(VENV_BIN)/pip install -e .

dev: venv
	$(VENV_BIN)/python -m jobdone.cli --version || true

build: venv
	$(VENV_BIN)/pip install -e .
	$(VENV_BIN)/pip install pyinstaller pyyaml
	$(VENV_BIN)/pyinstaller --onefile -n $(APP_NAME) --hidden-import=yaml src/jobdone/cli.py

link: build
	mkdir -p $(HOME)/.local/bin
	ln -sf $(CURDIR)/dist/$(APP_NAME) $(HOME)/.local/bin/$(APP_NAME)
	@echo "Linked $(CURDIR)/dist/$(APP_NAME) -> $(HOME)/.local/bin/$(APP_NAME). Ensure \"$$HOME/.local/bin\" is in PATH."

clean:
	rm -rf build dist *.spec $(VENV_DIR)
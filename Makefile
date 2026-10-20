VENV   := .venv-build
PIP    := $(VENV)/bin/pip
PYI    := $(VENV)/bin/pyinstaller
PREFIX ?= $(HOME)/.local
BINDIR := $(PREFIX)/bin
LIBDIR := $(PREFIX)/lib/usirooms

# Shared pyinstaller flags
PYI_FLAGS := --noconfirm --clean --name usirooms --workpath build --specpath build

.PHONY: all venv build-dir build-one install uninstall clean

all: build-dir

$(PYI):
	python3 -m venv $(VENV)
	$(PIP) -q install --upgrade pip pyinstaller

venv: $(PYI)

# Recommended artifact: directory bundle, ~0.1s startup
build-dir: $(PYI)
	$(PYI) --onedir $(PYI_FLAGS) --distpath dist-dir usi_rooms.py
	codesign -s - --force --deep dist-dir/usirooms/usirooms 2>/dev/null || true
	@du -sh dist-dir/usirooms | sed 's/^/built: /'

# Portable single file, ~4s startup (unpacks itself on every run)
build-one: $(PYI)
	$(PYI) --onefile $(PYI_FLAGS) --distpath dist usi_rooms.py
	codesign -s - --force dist/usirooms 2>/dev/null || true
	@ls -lh dist/usirooms | awk '{print "built: " $$5 " " $$9}'

install: build-dir
	mkdir -p $(BINDIR) $(LIBDIR)
	rm -rf $(LIBDIR)/*
	cp -R dist-dir/usirooms/. $(LIBDIR)/
	ln -sf $(LIBDIR)/usirooms $(BINDIR)/usirooms
	@echo "installed $(BINDIR)/usirooms -> $(LIBDIR)/usirooms"

uninstall:
	rm -rf $(LIBDIR) $(BINDIR)/usirooms

clean:
	rm -rf build dist dist-dir $(VENV)

# evilo-local-source

Generate signed test manga plugins for Evilo. Each plugin contains invented
comics, searchable titles, chapters, and PNG reader pages. Start with **2 plugins**,
not 600.

## Before starting

You need Python 3.10+, Git, JDK 21, and `evilo-plugin-template` next to this
repository. The first build needs network access to download Gradle, SDK, and
Wasmline dependencies.

Run the commands below from this repository. Set up Pillow once:

```sh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install 'Pillow>=10.1'
```

Activate `.venv` in each new terminal used for generation.

## 1. Create your local signing keys — once

```sh
python3 -I scripts/setup_signing.py "$HOME/.evilo/local-fixture-signing"
```

This creates these files **on your computer**, outside the repository:

```text
~/.evilo/local-fixture-signing/
  private.key
  public.key
  authority.properties
```

Keys are not included in the repository. This command creates your own random
local test keys; it does not need an official Evilo private key or change the
app's built-in key. Keep the directory private and reuse it for later generations.
If the command says the directory already exists, do not run it again or delete
working keys; continue with your existing fixture keys.

## 2. Generate two plugins

**Testing on the same computer:**

```sh
bash gen.sh --base-url http://127.0.0.1:8080 --count 2 \
  --signing-key-directory "$HOME/.evilo/local-fixture-signing" \
  --auto-download
```

**Testing on a phone over Wi-Fi:** replace `192.168.1.20` below with your
computer's LAN IP. The phone and computer must be able to reach each other.

```sh
bash gen.sh --ip 192.168.1.20 --port 8080 --count 2 \
  --signing-key-directory "$HOME/.evilo/local-fixture-signing" \
  --auto-download
```

Choose **one** command. Wait for generation to finish successfully before starting
the server. This step compiles real plugins; it can take time, especially on the
first run.

## 3. Start the server

In another terminal, from this repository:

```sh
python3 -I serve.py 8080
```

Keep this terminal running. Stop it with `Ctrl+C` when finished. The server serves
`build/`, never your signing-key directory, and listens on all IPv4 interfaces.

## 4. Open the source in Evilo

Select Manga, open Sources, and add the URL matching step 2:

| Where Evilo runs | URL to add |
| --- | --- |
| Same computer | `http://127.0.0.1:8080/repo.json` |
| Phone over Wi-Fi | `http://192.168.1.20:8080/repo.json` — use your computer's IP |

Allow HTTP and, if requested, local-network access. Choose a plugin, review its
publisher fingerprint, approve installation, then open a comic and a chapter.
The test publisher is separate from the official publisher; signature verification
still applies.

## What does localhost mean?

`localhost` and `127.0.0.1` mean **the device running Evilo**, not automatically
your computer. A phone using that address connects to the phone itself.

For an Android phone connected through ADB, you can instead use the computer-only
generation command in step 2 and forward the port:

```sh
adb reverse tcp:8080 tcp:8080
```

Then add `http://127.0.0.1:8080/repo.json` on the phone. Keep ADB connected and the
server running. When finished:

```sh
adb reverse --remove tcp:8080
```

## Common problems

- **Cannot open `repo.json`:** first try the same URL in the target device's browser.
  Check that the server is running, the address is the computer's IP for Wi-Fi,
  and the firewall allows TCP 8080. LAN permissions and HTTP consent in Evilo are
  also required where applicable.
- **IP or port changed:** generate again with the new address. Editing only
  `repo.json` is insufficient because plugins also contain cover and page URLs.
- **Signing directory missing:** complete step 1, then use the same path in step 2.
- **SDK dependency not found:** if you already published the matching SDK to
  Maven Local, add `--use-local-sdk` to generation. This flag does not publish it.
- **Port 8080 busy:** choose another port in both generation and `serve.py`.

[Advanced reference](docs/advanced.md): all options, build/signing details,
generated files, regression commands, and the cost of generating 600 plugins.

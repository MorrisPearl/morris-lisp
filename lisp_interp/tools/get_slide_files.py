"""Downloads, once, the files that a slideshow made by notebook-to-slides needs, so that the slideshow works with no internet connection.

    python3 tools/get_slide_files.py

They go in slides_support/ next to lisp_interpreter.py (which git ignores). Each download is checked against the hash that the
place it comes from publishes for it, and nothing is kept if it does not match:

    reveal.js 4.0.2   the slideshow itself (MIT licence)          from the npm registry, registry.npmjs.org
    require.js 2.1.10 loads reveal.js into the page               from cdnjs, cdnjs.cloudflare.com
    jQuery 2.0.3      which the page loads, though reveal.js does not use it   from cdnjs

These are the versions that nbconvert's slide template names, so the page it makes is the same as it makes with the internet."""
import base64
import hashlib
import io
import json
import os
import tarfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DESTINATION = os.path.join(HERE, "..", "slides_support")

REVEAL = ("reveal.js", "4.0.2")
CDNJS = [("require.js", "2.1.10", "require.min.js"), ("jquery", "2.0.3", "jquery.min.js")]

# What of reveal.js is kept: its scripts and styles, and the speaker notes plugin that the slide template names.
REVEAL_KEEP = ("package/dist/", "package/plugin/notes/", "package/LICENSE")


def get(url):
    """The bytes at the url."""
    request = urllib.request.Request(url, headers={"User-Agent": "morris_lisp get_slide_files"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def check(data, integrity, what):
    """An error unless the bytes have the hash in integrity, written as algorithm-base64, such as sha512-...."""
    algorithm, _, expected = integrity.partition("-")
    found = base64.b64encode(hashlib.new(algorithm, data).digest()).decode()
    if found != expected:
        raise SystemExit("%s does not have the hash its publisher gives (%s): nothing was kept" % (what, integrity))


def get_reveal():
    name, version = REVEAL
    published = json.loads(get("https://registry.npmjs.org/%s/%s" % (name, version)))
    data = get(published["dist"]["tarball"])
    check(data, published["dist"]["integrity"], "%s %s" % (name, version))
    folder = os.path.join(DESTINATION, "reveal.js")
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive.getmembers():
            if member.isfile() and member.name.startswith(REVEAL_KEEP):
                path = os.path.join(folder, member.name[len("package/"):])
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(archive.extractfile(member).read())
    print("reveal.js %s: %d bytes downloaded, in %s" % (version, len(data), os.path.normpath(folder)))


def get_from_cdnjs(library, version, filename):
    published = json.loads(get("https://api.cdnjs.com/libraries/%s/%s?fields=sri" % (library, version)))
    data = get("https://cdnjs.cloudflare.com/ajax/libs/%s/%s/%s" % (library, version, filename))
    check(data, published["sri"][filename], "%s %s" % (library, version))
    with open(os.path.join(DESTINATION, filename), "wb") as f:
        f.write(data)
    print("%s %s: %d bytes downloaded, in %s" % (library, version, len(data), os.path.normpath(os.path.join(DESTINATION, filename))))


def main():
    os.makedirs(DESTINATION, exist_ok=True)
    get_reveal()
    for library, version, filename in CDNJS:
        get_from_cdnjs(library, version, filename)


if __name__ == "__main__":
    main()

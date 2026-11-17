# Security

House Lights is a small program for a home network. It has **no login**: anyone who can open
the page can control the lights, change the settings and add controllers. That is on purpose,
so keep it on your home network and **never forward its port to the internet**. See "Good to
know" in the [README](README.md).

## Reporting a problem

Please report security problems **privately**, not in a public issue:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**.

Say what you found, how to repeat it, and what it lets someone do. This is a hobby project, so
replies are best effort, but every report gets read.

If there is no **Report a vulnerability** button, open an ordinary issue that says only that
you have a security report (no details) and a private way to talk will be arranged.

## What counts

Reports that help:

- A web page, a shared themes file or another website that can make the dashboard do something
  the person using it didn't intend.
- A way to read or change files outside the settings folder, or to read the stored Tuya keys.
- Commands going to devices that weren't chosen.

Not security bugs:

- The dashboard having no password on your own network (that is by design).
- Anything that needs access to the computer it runs on or to its settings folder.

## Supported versions

Only the latest version on the `main` branch gets fixes.

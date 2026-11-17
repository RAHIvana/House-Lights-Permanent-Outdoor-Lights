# Contributing

Thanks for helping. The most useful things, in order:

1. **Controller reports.** Tried House Lights on a controller that isn't marked as tested? Open a
   "My controller works / doesn't" issue and say what happened, whether it worked or not.
2. **Bug reports.** Use the bug report form, and remove addresses, device IDs and keys first.
3. **Themes.** Made one you love? Export it from the Themes tab and attach the `.json` file to an
   issue (or open a pull request that adds it as a built-in theme).
4. **Code.** Small, focused pull requests are easiest to review. Adding support for another
   controller? Start with the [drivers guide](houselights/drivers/README.md); how the setup wizard
   uses a driver is in [docs/light-discovery.md](docs/light-discovery.md).

Security problems go through [SECURITY.md](SECURITY.md), not a public issue.

## Working on the code

```sh
venv/bin/python -m houselights --dry        # practice mode: nothing is sent to any light
venv/bin/python tools/fake_govee.py         # simulated controllers (see the README)
```

Windows: `venv\Scripts\python`. Run the tests before you open a pull request; they need no lights:

```sh
venv/bin/python tests/test_settings.py
venv/bin/python tests/test_setup.py
venv/bin/python tests/test_schedule.py
venv/bin/python tests/test_themes.py
venv/bin/python tests/test_drivers.py
venv/bin/python tests/test_security.py
venv/bin/python tests/test_stream.py
venv/bin/python tests/test_auth.py
venv/bin/python tests/test_scripts.py
```

Ground rules:

- Plain Python. No compiled dependencies, and no new required packages without discussing it first.
- **Never test against someone else's lights.** Use `--dry` or the simulators in `tools/`.
- No private data in the repository: no real IP addresses (examples use `192.168.2.x`), names,
  locations, device IDs or MAC addresses.
- Added or changed a built-in theme? Run `python tools/make_theme_gallery.py` and commit the
  result; a test checks that the gallery page and its pictures are up to date.

## License

By sending a contribution you agree that it is licensed under the same terms as the project
(see [LICENSE](LICENSE)).

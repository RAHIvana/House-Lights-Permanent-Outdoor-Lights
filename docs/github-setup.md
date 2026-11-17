# Making the repository public: everything to do on GitHub

A checklist for the repository owner, in the order to do things. Tick the boxes as you go.

How reliable the click paths are: they were checked against GitHub's own documentation on
2026-11-17 and against screenshots of this repository's Settings pages, but GitHub renames buttons
now and then. Where a label is from memory and not from the docs it says **(confirm in the app)**.
While the repository is **private** on a free plan, several settings do not appear at all (the pages
show only the free ones): those are marked **(public only)** and are done right after the switch.

## At a glance

1. **Decide the name** (section 1), then rename and update the README if needed.
2. **Your account:** two-factor authentication, private email (section 3).
3. **Repository settings while private:** About box, Dependabot, Features, Commits, labels, Actions (section 3).
4. **Tests:** make sure Actions is on and the `tests` workflow is green on Python 3.10 and 3.13 (section 4).
5. **Make it public** (section 5).
6. **Right after:** private vulnerability reporting, secret scanning, a ruleset for `main`, issues open to
   everyone, the social image (section 6).
7. **Look at it as a stranger** (section 7).

## 1. Decide the name (still open)

Decided: the product is called **House Lights**, and "permanent outdoor lights" stays next to it
because it describes what the project is for. Open: the one-line description (tagline) and the
repository name.

**Tagline** (used in the About box, the first line of the README and the social image):

| # | Tagline |
|---|---|
| 1 | **House Lights: themes and schedules for permanent outdoor lights** (recommended: says what it is and what you get) |
| 2 | House Lights: a dashboard for permanent outdoor lights, free for home use (it is under a noncommercial license, so say "free for home use", not just "free") |
| 3 | House Lights: holiday themes and your own designs for permanent outdoor lights |

**Repository name** (now `Permanent-Outdoor-Light-Controller`):

| | Name | Why |
|---|---|---|
| A | **`house-lights`** (recommended) | Short, matches the product name. "Permanent outdoor lights" lives in the About text, the topics, the first line of the README and the social image. |
| B | Keep `Permanent-Outdoor-Light-Controller` | Nothing to change, and the phrase is in the address. |

Notes:

- Before the repository is public is the cheapest time to rename: nobody has the address yet. GitHub
  redirects the old name afterwards anyway.
- Keep brand names (Govee, WLED, Tuya) out of the name and the logo. The README already says the
  project is not affiliated with them.
- If you rename (A), these must change: the repository name (Settings, General, Repository name,
  Rename), the clone address in `README.md` (two places) and `README_Raspberry.md` (one place),
  your local remote (`git remote set-url origin git@github.com:RAHIvana/<new-name>.git`), the Website
  link in the About box, and the tests badge if you add one (section 4).

- [ ] Tagline chosen: ______
- [ ] Repository name chosen: ______
- [ ] If renamed: README clone commands, Raspberry Pi guide and local remote updated and pushed

## 2. Already done and checked

For the record, so you don't repeat it:

- [x] **History scan:** the whole history (64 commits when checked on 2026-11-17) searched for keys, tokens, MAC
  addresses, ZIP code, house names, emails and non-example addresses. Found only made-up and test
  addresses (`192.168.2.x`, `192.168.5.x`, the fake MAC `00:00:00:00:00:01`, and the example addresses in
  the security tests).
- [x] **Commit identity:** every commit and both tags use `297153960+RAHIvana@users.noreply.github.com`
  and the name RAHIvana. Your real name appears nowhere in files, history, commit messages or tags.
- [x] **Nothing private tracked:** no `data/`, no `*.json` (they are in `.gitignore`).
- [x] **License:** PolyForm Noncommercial 1.0.0 in `LICENSE`, and the notice the MIT-licensed Tabler
  icon requires in `THIRD_PARTY_NOTICES.md`.
- [x] **Files GitHub looks for:** `README.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, two issue forms
  (bug report, "My controller works / doesn't") and the tests workflow in `.github/workflows/`.
- [x] **Web security fixes:** script injection through theme names, Host and Origin checks, security
  headers and home-network-only addresses, with a test (`tests/test_security.py`).

## 3. While the repository is still private

### Your account

- [ ] **Two-factor authentication** is on (profile picture, Settings, Password and authentication).
- [ ] Profile picture, Settings, **Emails**: tick **Keep my email addresses private** and **Block command
  line pushes that expose my email**. Commits already use the noreply address; this keeps it that way.

### The repository's Settings

Settings is the tab in the repository's top bar (under **...** if it is hidden).

- [ ] **About box** (main page, the gear to the right of **About**): the description (up to 350
  characters, below), the Website (the gallery page, after the name is final) and **Topics**.
  Topics are lowercase letters, numbers and hyphens, at most 50 characters each and 20 in all.
  Untick **Packages** and **Deployments** if the box shows them (confirm in the app).

  Suggested description (with tagline 1, 197 characters):

  > Themes and schedules for permanent outdoor lights (Govee, WLED and more): 106 holiday and everyday
  > themes, animated light by light, plus your own designs. Free for home and other noncommercial use.

  Suggested topics (12): `permanent-outdoor-lights`, `govee`, `wled`, `holiday-lights`, `christmas-lights`,
  `halloween`, `diwali`, `led-lights`, `home-automation`, `smart-home`, `python`, `fastapi`

  Website: `https://github.com/RAHIvana/<name>/blob/main/docs/themes.md`

- [ ] **Settings, Security and quality, Advanced Security** (free for private repositories): switch on
  **Dependency graph** first, then **Dependabot alerts** and **Dependabot security updates**. **Grouped
  security updates** is optional (one pull request per package manager instead of many). Leave **Dependabot
  version updates** (the **Create dependabot.yml** button) and **Runner type** alone.
- [ ] **Settings, General, Features:** **Issues** stays on. Leave **Wikis**, **Sponsorships** and **Projects** off,
  and **Discussions** off until you want a place for "show your house" posts. Do **not** press **Set up
  templates**: the two issue forms are already in the repository and appear by themselves.
- [ ] **Settings, General, Commits:** untick **Allow comments on individual commits** (once public, anyone with a
  GitHub account could comment on any commit). **Require contributors to sign off on web-based commits** can stay on.
- [ ] **Settings, General, Pull Requests:** nothing needed. **Automatically delete head branches** is a
  nice-to-have. **Allow auto-merge** stays greyed out until there are rules with required checks.
- [ ] **Labels** (Issues tab, **Labels**, **New label**): create **`controller-report`**. The "My controller works /
  doesn't" form adds it to new issues only if it exists. **`bug`** is one of GitHub's default labels; check it
  is still there.
- [ ] **Review what is attached:** Settings, Collaborators; Deploy keys; Webhooks; Secrets and variables. Nothing there
  you don't recognise. (Anything stored there stays private, but check.)
- [ ] **Actions settings:** see section 4.

## 4. Tests on GitHub (GitHub Actions)

### What is already in the repository

`.github/workflows/tests.yml` is a workflow named **tests**:

- **When it runs:** on every push to `main`, on every pull request, and by hand (a **Run workflow** button,
  added with this checklist).
- **What it does:** on two Python versions (**3.10** and **3.13**, the README says "3.10 or newer") it checks
  out the code, installs `requirements.txt`, and runs the six test files: `test_settings`, `test_setup`,
  `test_schedule`, `test_themes`, `test_drivers` and `test_security`. They need no lights, no network (the ZIP
  lookup is faked) and no secrets, and the workflow has read-only permission on the repository.
- **Where it shows up:** the repository's **Actions** tab, and as a green tick or red cross next to every commit.
  The two checks are named `test (3.10)` and `test (3.13)`.

### Turning it on

Nothing needs switching on per workflow: a workflow file on the default branch runs by itself, and the
file was pushed with the last commit. What can stop it is the repository's Actions permission.

- [ ] **Settings, Actions, General, Actions permissions:** actions are allowed. For the safest choice use
  **Allow OWNER, and select non-OWNER, actions and reusable workflows** and allow actions created by GitHub
  (the workflow uses only `actions/checkout` and `actions/setup-python`) (confirm the wording in the app).
- [ ] **Same page, Approval for running fork pull request workflows from contributors:** choose **Require
  approval for all external contributors** (the safest of the three; the default only asks first-time
  contributors). It matters once the repository is public and strangers can open pull requests.
- [ ] **Same page:** leave **Require actions to be pinned to a full-length commit SHA** unticked. The workflow
  uses version tags (`@v4`, `@v5`), and the box would make it fail.
- [ ] If the Actions tab says workflows are disabled, or `tests` shows as disabled in its left-hand list, enable
  them (the Actions tab shows a button; a single workflow has an **Enable workflow** entry in its **...** menu)
  (confirm in the app).

### Checking the first run

- [ ] Open the **Actions** tab, then **tests**, then the latest run. Both jobs, `test (3.10)` and
  `test (3.13)`, should be green.
- If one is red: open it, expand the red step and read the last lines. Python 3.10 is the likeliest culprit,
  because it was only checked by searching for newer features, never run. Fix, push, or press **Re-run failed
  jobs**. **Do this before going public:** run logs become public with the repository.
- To start the tests by hand: **Actions, tests, Run workflow**, pick `main`, **Run workflow**.
- Private repositories use a monthly allowance of free Actions minutes and public repositories run on standard
  runners free; the limits change, so check Settings, Billing if runs ever stop.

### Showing the result in the README (after the name is final)

- [ ] Add this line under the README title, with the real repository name (it appears green or red):

  ```
  [![tests](https://github.com/RAHIvana/<name>/actions/workflows/tests.yml/badge.svg)](https://github.com/RAHIvana/<name>/actions/workflows/tests.yml)
  ```

### Making the tests a gate (optional, probably later)

A ruleset rule **Require status checks to pass** (Settings, Rules, Rulesets; the checks `test (3.10)` and `test (3.13)`
appear in its list only after a run has happened) stops a change from landing on `main` until both are green.
The catch (confirm in the app): with required checks, changes have to arrive through a **pull request**; a direct
push to `main`, which is how the repository is worked on today, is refused because its checks haven't run yet.
Recommendation: leave it off until you decide to work through pull requests, even your own. The green tick on
every commit already tells you.

### Keeping the tests honest

- Adding a test file? Add a `- run:` line for it in `tests.yml`, or it never runs on GitHub.
- The gallery test fails when a theme was added or changed and `docs/themes.md` and its pictures weren't
  redrawn: run `python tools/make_theme_gallery.py` and commit the result.
- To run exactly what GitHub runs: the six commands listed in `CONTRIBUTING.md`.

## 5. Switching to public

Do these first:

- [ ] Name decided and, if renamed, everything in section 1 pushed.
- [ ] Sections 3 and 4 finished, and the Actions run is green.

Then: **Settings, General, scroll to the Danger Zone, Change repository visibility, Change visibility,
Make public.** GitHub asks you to type the repository name and to tick **I have read and understand these
effects**. What it tells you changes:

- The code and the whole history are visible to everyone, and anyone can fork it. (Forks cannot be
  switched off, and the license is what limits what people may do with the code.)
- Push rulesets are disabled (branch rulesets are created after the switch, below).
- Actions history and logs become visible.
- Stars and watchers are erased.

Going back to private later does not pull anything back: forks that were made while it was public stay
public.

## 6. Right after it is public

These settings appear only now.

- [ ] **Settings, Security and quality, Advanced Security:** **Private vulnerability reporting: Enable** (this
  makes the **Report a vulnerability** button that `SECURITY.md` points to), **Secret scanning: Enable**,
  **Push protection: Enable**. CodeQL code scanning is optional.
- [ ] **A ruleset for `main`:** Settings, **Code, planning, and automation**, **Rulesets**, **New ruleset**, **New branch
  ruleset**. Name it (for example "Protect main"), set **Enforcement** to **Active** (it starts as Disabled), under
  **Target branches** choose **Add a target** and include the default branch, then in **Branch rules** tick the
  rules that restrict deletions and block force pushes (confirm the names in the app), and **Create**.
  This matters once other people have cloned: rewriting history would break their copies. Leave the
  required-status-checks rule off for now (section 4).
- [ ] **Settings, General, Features, Issues:** make sure issue creation is open to everyone. While private it
  showed "Creation allowed by: Collaborators only", greyed out.
- [ ] **Social preview:** Settings, **Social preview**, **Edit**, **Upload an image**. PNG, JPG or GIF, under 1 MB, at
  least 640 by 320 pixels, 1280 by 640 shows best; a solid background is safest. It only shows for public
  repositories. (A simple one: the bulb logo, the name and a few theme strips; it can be made with the tools
  in the repository.)
- [ ] Optional: **Discussions** on, if you want "show off your house" posts and questions kept out of Issues.

## 7. Check it as a stranger

Open the repository in a private or incognito window where you are signed out:

- [ ] The README renders, the gallery page (`docs/themes.md`) loads and its strips **move**.
- [ ] The clone command from the README works as written (try it in an empty folder).
- [ ] **New issue** offers the two forms; the **Security** tab has **Report a vulnerability**.
- [ ] The sidebar shows the license, and the About box shows the description and topics.
- [ ] **Insights, Community standards** shows description, README, license, contributing, security policy and
  issue templates as done.
- [ ] The Actions tab shows green runs (and the README badge, if you added it, says passing).

## 8. Later, if you want

- GitHub **Releases** from the existing tags (`v2_0`, `v2_1`). The tag style is yours to choose.
- A `dependabot.yml` that keeps the GitHub Actions versions fresh.
- A Developer Certificate of Origin line in `CONTRIBUTING.md` (you have the web sign-off setting on) and,
  if you ever want to offer commercial licenses, contributors' agreement to that.
- A Code of Conduct and a pull request template (the Community standards page lists both).
- An optional password for the dashboard (it has none today, by design; see `SECURITY.md`).

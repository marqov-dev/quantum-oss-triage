# Disclosure policy

Every finding with security impact is private, whatever its severity and
whichever skill or scanner raised it. In round one that includes known
dependency advisories.

## How security findings are reported

- Through GitHub private vulnerability reporting, where the repository has it
  turned on. We always tick the box declaring AI assistance.
- Otherwise, to the contact in `SECURITY.md`, or to the company's own
  vulnerability reporting process.
- Security fixes are never pushed to a public branch. They are attached to the
  private report as a `.patch` file, or offered through GitHub's temporary
  private fork once the maintainer opens one.

Security reports are free and unconditional. No payment, sign-up or
commercial relationship is ever needed to receive details or to have a
disclosure handled properly. We do not publish details ourselves; the
maintainer decides when and how to disclose.

If a maintainer has not acknowledged a report within 14 days, we follow up
personally once. In round one we do not escalate publicly.

## What is public and what is not

A share link is a bearer link: anyone it is forwarded to can read it. So
security details are kept out of share links as well as out of public forks.

Public, per project:

- counts of validated security vulnerabilities, with newly found ones and
  known advisories counted separately;
- their severity and the date each was reported privately.

Never public, and never in a share link: code locations, exploit details,
secret values, patches and raw model outputs. Unvalidated suspicions are
never counted.

The publisher refuses to write a report if its automated check finds the
location, title or claim of a sensitive finding, secret-like values, exploit
wording or email addresses. A person still reads every public title and
summary for details given away indirectly.

## Other findings

Non-security findings go in the repository's private Report, shared with that
team. Fixes sit on branches named `review/2026-10/<finding-id>` in a public
fork under `marqov-dev`, pushed only after a person approves each branch. We
open no pull requests or issues against the original repository.

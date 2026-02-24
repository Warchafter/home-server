# Project Instructions

## Identity & Git Attribution

- This is a **personal project**. All commits must use the personal identity:
  - **Email:** kevin.arriaga@gmail.com
  - **Username:** Warchafter
- Before any `git commit` or `git push`, verify with `git config user.email` that it returns the personal email.
- Remote URL must use the personal SSH alias: `git@github-personal:Warchafter/home-server.git`
- Do **not** use `git@github.com` directly — it maps to the work SSH key.

## Environment Isolation

- All file reads and searches must be restricted to this project directory (`~/Personal/home-server/`).
- Do **not** pull context, environment variables, or snippets from `~/work/` or any work-related directories.
- Do **not** use company-specific Jira tags, internal ticket formatting, or work conventions in commit messages.

## Commit Style

- Keep commit messages clean and personal-project appropriate.
- Use conventional commit style (e.g., `feat:`, `fix:`, `docs:`, `chore:`).
- **Never** add `Co-Authored-By` lines to commit messages.

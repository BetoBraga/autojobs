# autojobs v2.9.2 - Remote and worldwide search intent

- Clarifies that search location is never hard-coded to Dublin.
- Fresh installs default to `Worldwide` instead of a city-specific target.
- Empty location lists normalize to `Worldwide`, avoiding accidental city lock-in.
- Broad aliases such as `Remote`, `Worldwide`, `Global`, and `Anywhere` resolve to the LinkedIn `Worldwide` search scope. Use the Remote work-type filter for remote-only runs.
- Maximum Coverage now preserves work-type filters, so a user-selected Remote-only campaign stays Remote-only.
- Search UI help now explicitly lists examples for cities, countries, remote, worldwide, and multi-country campaigns.
- Responsive reflow now updates every scrollable page's viewport width after a window resize or tab change, including Custom answers.

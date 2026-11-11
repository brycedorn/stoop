# Your runs (optional)

Put GPS files of your own runs here: GPX, TCX or FIT (gzipped `.gz` is fine), from any app or watch,
in any subfolders. They feed the "where you actually run" part of the Running factor.

- A file that records its sport (GPX `<type>`, TCX `Sport`, FIT `sport`) is used only if it's a run.
  Files that don't say are used as-is, so leave out rides and walks.
- `.fit` files need `pip install -e ".[activities]"`.
- Rerun: `python -m stoop run --steps running`

Everything in this folder except this README is gitignored.

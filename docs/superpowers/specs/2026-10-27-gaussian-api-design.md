# Gaussian analysis API

User-approved scope: refactor the independent camera profile scripts into
qtools.calc.gaussian, using existing NumPy/SciPy dependencies. Preserve the
common Profile entry points and add array/path fitting, structured results,
explicit units, multi-beam detection, lazy plotting and a module CLI.

## Public contract

- Both qtools.calc.gaussian and from qtools.calc import gaussian work.
- fit(source, n_beams=1, pixel_size=1.0, unit="px", ...) accepts 2D arrays,
  standard images, and RAW paths. RAW shape is (height, width); omission only
  infers exact 4:3 images. Support 8-bit and little-endian 16-bit RAW.
- Every fit returns GaussianFitResult with a tuple of BeamParameters, background,
  optimizer diagnostics, full-image residual metrics, evaluation and plotting.
- Beam/model values use pixels and radians. to_dict() and plot coordinates
  scale lengths by pixel_size into the explicitly supplied unit. Sigma means
  standard deviation; waist means 1/e² intensity radius (2 sigma).
- Rotating fits order axes by major/minor width and normalize angles. Fixed
  theta keeps x/y axes. Multi-beam results sort by (x, y) for stable ordering.
- Keep Profile loading, moments, fitted/fitted_multi_beam and gauss_flat imports.
  Result values and best_fit remain available, but no lmfit emulation.

## Implementation and validation

1. Add lazy package exports, validated image IO and result types.
2. Fit bounded positive-width Gaussian components plus one shared background
   with scipy.optimize.least_squares and an analytical Jacobian. Initialize
   from moments and separated local maxima, preserving 16-bit/float data.
   Expose configurable peak threshold/distance and deterministic sampling;
   report sample_step and allow full-resolution fitting.
3. Separate plotting/CLI from numerical imports. Plot slices using the complete
   rotated multi-beam model. Modernize the beam-removal helper without changing
   the supplied RAW files or notebook.
4. Test lazy imports, analytic parameter recovery, rotation, 16-bit and signed
   data, single/multiple peaks, invalid inputs, unit conversion, plotting, RAW
   IO and CLI. Smoke-test both existing RAW samples and relevant regressions.

No new dependency, hardware access, git commit, or changes to unrelated work.

## Validation results

- Gaussian and camera regression suites: 55 tests passed.
- Both supplied 1440 x 1080 RAW samples converge in seven optimizer evaluations.
  Default sampling used stride 4; full-resolution reference fits gave maximum
  center differences of 0.0176 px (single) and 0.0454 px (double), and maximum
  sigma differences of 0.0103 px and 0.0315 px respectively.
- The double-beam figure was rendered and visually inspected with the full
  model used for slices, correct physical axes, and 1/e² contours.
- Additional SLM regression collection is blocked by a missing pre-existing
  imageio dependency in the local environment. No SLM code was changed.

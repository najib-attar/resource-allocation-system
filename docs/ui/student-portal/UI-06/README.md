# UI-06 Waiting Lists

Overview, queue detail and policy use the approved student service layout. Queue
rows preserve resource kind, owning faculty, exact interval, review status and
contextual estimated/eligible position. Detail separates review from recorded
assignment and explicitly states that preapproval reserves nothing. Current
policy version, accepted time, configured notice, requirements, withdrawal and
history remain visible. Staff review and priority controls retain their guards.

The assigned-request link opens its current source record; it does not claim that
an old assignment still has a confirmed current status. Equipment assignment still
requires physical collection. No minimum notice default or alternate queue policy
is introduced.

Real browser checks cover populated, empty and private/forbidden states at all four
widths, keyboard/focus/overflow and CSRF. A synthetic queue was withdrawn, then a
new eligible unavailable room request was submitted through the actual form,
preapproved by its responsible staff account and assigned after staff released a
compatible room. The assigned link opened the confirmed request; assignment was
captured at all four widths.

Exact automated results and test names are in `tests.json` / `tests.txt`. The final
complete rerun uses the two actual waiting-list classes, including their Flask
tests. An earlier command mistakenly named an additional nonexistent class; that
launcher error was corrected, and its attempt is retained under ignored build
artifacts rather than counted as a product test or a passing verification.

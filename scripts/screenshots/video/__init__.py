"""Video pipeline — stitch screenshots + docs + (later) recordings into MP4.

Phase B1 ships `kind: still` only; `doc_hero`, `doc_callout`, `playwright`, and
`manual` are reserved in the schema and raise NotImplementedError at render
time with their phase number in the message.
"""

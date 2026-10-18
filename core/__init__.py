"""EchoForge — Core business-logic package.

This package contains modules that operate on data already retrieved from the
graph database and produce higher-level, domain-meaningful results:

* ``comparison`` — structured diff between an actual Decision and a
  hypothetical ScenarioBranch, including display-ready formatting for
  Streamlit panels.

The ``core`` package depends on the ``db`` package for raw graph access but
must NEVER write to nodes whose ``is_actual`` property is ``True``.
Immutability enforcement is delegated to ``db.history``.
"""

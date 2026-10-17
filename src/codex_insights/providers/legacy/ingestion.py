"""Retired collection entry point; retain accepted facts without reading archives."""

def refresh_source(store, source, report, cancel=None, progress=None, rebuild=False):
    with store.connect() as db:
        db.execute("UPDATE sources SET status='Collection disabled',detail='Encrypted archive collection is retired. Previously indexed history is retained.' WHERE id=?", (source['id'],))

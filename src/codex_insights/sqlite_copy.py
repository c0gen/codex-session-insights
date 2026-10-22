"""Column-name-safe copies between independently migrated SQLite schemas."""


def quoted(value):
    return '"' + value.replace('"', '""') + '"'


def insert_from(db, table, schema, where='', args=(), mode=''):
    columns = [row['name'] for row in db.execute('PRAGMA table_info(' + quoted(table) + ')')]
    names = ','.join(quoted(column) for column in columns)
    db.execute('INSERT ' + mode + ' INTO ' + quoted(table) + '(' + names + ') SELECT ' + names +
               ' FROM ' + quoted(schema) + '.' + quoted(table) + (' WHERE ' + where if where else ''), args)

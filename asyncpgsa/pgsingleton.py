from .pool import create_pool
from .connection import compile_query
from .record import Record
"""
this is a high level singleton for managing a pool
"""


class NotInitializedError(Exception):
    pass


class PG:
    __slots__ = ('__pool',)

    def __init__(self):
        self.__pool = None

    @property
    def pool(self):
        if not self.__pool:
            raise NotInitializedError('pg.init() needs to be called '
                                      'before you can make queries')
        else:
            return self.__pool

    async def init(self, *args, **kwargs):
        """
        :param args: args for pool
        :param kwargs: kwargs for pool
        :return: None
        """
        self.__pool = await create_pool(*args, **kwargs)

    def query(self, query, *args, prefetch=None, timeout=None):
        """
        make a read only query. Ideal for select statements.
        This method converts the query to a prepared statement
        and uses a cursor to return the results. So you only get
        so many rows at a time. This can dramatically increase performance
        for queries that have a lot of results/responses as not everything has
        to be loaded into memory at once
        :param query: query to be performed
        :param args: parameters to query (if a string)
        :param callback: a callback to call with the responses
        :param int prefetch: The number of rows the *cursor iterator*
                             will prefetch (defaults to ``50``.)
        :param float timeout: Optional timeout in seconds.
        :return:
        """
        compiled_q, compiled_args = compile_query(query)
        query, args = compiled_q, compiled_args or args
        con_manager = self.pool.transaction(readonly=True,
                                            isolation='serializable')

        return QueryContextManager(con_manager, query, args,
                                   prefetch=prefetch, timeout=timeout)

    async def fetch(self, query, *args, timeout=None, **kwargs):
        async with self.pool.transaction(**kwargs) as conn:
            return await conn.fetch(query, *args, timeout=timeout)

    async def fetchrow(self, query, *args, timeout=None, **kwargs):
        async with self.pool.transaction(**kwargs) as conn:
            return await conn.fetchrow(query, *args, timeout=timeout)

    async def fetchval(self, query, *args, timeout=None, column=0, **kwargs):
        async with self.pool.transaction(**kwargs) as conn:
            results = await conn.fetchval(
                query, *args, column=column, timeout=timeout)
        return results

    async def insert(self, *args, id_col_name: str = 'id',
                     timeout=None, **kwargs):
        async with self.pool.transaction(**kwargs) as conn:
            return await conn.insert(
                *args,
                id_col_name=id_col_name,
                timeout=timeout)

    def transaction(self, **kwargs):
        # not async because this returns a context manager
        return self.pool.transaction(**kwargs)

    def begin(self, **kwargs):
        """
        alias for transaction
        """
        return self.transaction(**kwargs)


class QueryContextManager:
    __slots__ = ('cm', 'query', 'args', 'prefetch', 'timeout', 'cursor')

    def __init__(self, con_manager, query, args=None,
                 prefetch=None, timeout=None):
        self.cm = con_manager
        self.cursor = None
        self.query = query
        self.args = args
        self.prefetch = prefetch
        self.timeout = timeout

    def __enter__(self):
        raise SyntaxError('Must use "async with"')

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    async def __aenter__(self):
        con = await self.cm.__aenter__()
        ps = await con.prepare(self.query, timeout=self.timeout)
        self.cursor = ps.cursor(*self.args, prefetch=self.prefetch,
                                timeout=self.timeout)
        return CursorInterface(self.cursor)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cm.__aexit__(exc_type, exc_val, exc_tb)


class CursorIterator:
    __slots__ = ('iterator',)

    def __init__(self, iterator):
        self.iterator = iterator

    def __getattr__(self, item):
        return getattr(self.iterator, item)

    def __aiter__(self):
        return self

    async def __anext__(self):
        return Record(await self.iterator.__anext__())


class CursorInterface:
    __slots__ = ('cursor', 'query')

    def __init__(self, cursor, query=None):
        self.cursor = cursor
        self.query = query

    def __aiter__(self):
        return CursorIterator(self.cursor.__aiter__())

    def __getattr__(self, item):
        return getattr(self.cursor, item)

    def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.query:
            self.query.__aexit(exc_type, exc_val, exc_tb)
        else:
            raise AttributeError('you shouldnt be here')



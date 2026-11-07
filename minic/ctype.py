"""Представлення типів мови C (підмножина MiniC).

CType(base, ptr, dims):
    base  – базовий тип: 'void' | 'char' | 'short' | 'int' | 'long' | 'float' | 'double'
    ptr   – рівень вказівника (int* -> 1, int** -> 2)
    dims  – розмірності масиву (int a[3][4] -> (3, 4)); None = невідомий розмір (параметр int a[])
"""

SIZES = {'void': 1, 'char': 1, 'short': 2, 'int': 4, 'long': 8, 'float': 4, 'double': 8}
INTEGER_BASES = ('char', 'short', 'int', 'long')
FLOAT_BASES = ('float', 'double')


class CType:
    __slots__ = ('base', 'ptr', 'dims', 'unsigned', 'const')

    def __init__(self, base='int', ptr=0, dims=(), unsigned=False, const=False):
        self.base = base
        self.ptr = ptr
        self.dims = tuple(dims)
        self.unsigned = unsigned
        self.const = const

    # ---- класифікація -------------------------------------------------
    @property
    def is_array(self):
        return bool(self.dims)

    @property
    def is_pointer(self):
        return self.ptr > 0 and not self.dims

    @property
    def is_void(self):
        return self.base == 'void' and self.ptr == 0 and not self.dims

    @property
    def is_integer(self):
        return not self.dims and self.ptr == 0 and self.base in INTEGER_BASES

    @property
    def is_float(self):
        return not self.dims and self.ptr == 0 and self.base in FLOAT_BASES

    @property
    def is_arith(self):
        return self.is_integer or self.is_float

    @property
    def is_scalar(self):
        return self.is_arith or self.is_pointer

    # ---- похідні типи --------------------------------------------------
    def element(self):
        """Тип елемента для a[i] або *p."""
        if self.dims:
            return CType(self.base, self.ptr, self.dims[1:], self.unsigned)
        if self.ptr:
            return CType(self.base, self.ptr - 1, (), self.unsigned)
        return None

    def pointer_to(self):
        return CType(self.base, self.ptr + 1, self.dims, self.unsigned)

    def decay(self):
        """Масив T[n] у виразі перетворюється на T* (лише для 1-вимірних)."""
        if len(self.dims) == 1:
            return CType(self.base, self.ptr + 1, (), self.unsigned)
        return self

    def size(self):
        if self.dims:
            n = 1
            for d in self.dims:
                n *= (d or 1)
            return n * CType(self.base, self.ptr, (), self.unsigned).size()
        if self.ptr:
            return 8
        return SIZES[self.base]

    def copy(self, **kw):
        t = CType(self.base, self.ptr, self.dims, self.unsigned, self.const)
        for k, v in kw.items():
            setattr(t, k, v)
        return t

    def __eq__(self, other):
        return (isinstance(other, CType) and self.base == other.base and self.ptr == other.ptr
                and self.dims == other.dims and self.unsigned == other.unsigned)

    def __hash__(self):
        return hash((self.base, self.ptr, self.dims, self.unsigned))

    def __str__(self):
        s = ('const ' if self.const else '') + ('unsigned ' if self.unsigned else '') + self.base
        s += '*' * self.ptr
        for d in self.dims:
            s += '[%s]' % ('' if d is None else d)
        return s

    __repr__ = __str__


INT = CType('int')
DOUBLE = CType('double')
CHAR = CType('char')
VOID = CType('void')
CHAR_PTR = CType('char', 1)


def arith_result(a, b):
    """Звичайні арифметичні перетворення (usual arithmetic conversions)."""
    if a.is_float or b.is_float:
        return CType('double')
    if a.base == 'long' or b.base == 'long':
        return CType('long', unsigned=a.unsigned or b.unsigned)
    return CType('int', unsigned=(a.unsigned and a.base == 'int') or (b.unsigned and b.base == 'int'))

"""Moving averages seeded from the first complete window."""


def seeded_average(series, window, *, alpha):
    seed = series.rolling(window).mean()
    first = seed.first_valid_index()
    if first is None:
        return seed
    updates = series.loc[first:].copy()
    updates.iloc[0] = seed.loc[first]
    return updates.ewm(alpha=alpha, adjust=False).mean().reindex(series.index)


def wilder_average(series, window):
    return seeded_average(series, window, alpha=1 / window)

from crypto import CryptoAdminCreate, CryptoAdminUpdate
from market_data import RegenerateBody


assert CryptoAdminCreate(symbol="X", name="X", price=1, volatilityHour=0.06).volatilityHour == 0.06
assert CryptoAdminUpdate(volatilityHour=0.06).volatilityHour == 0.06
assert RegenerateBody(market="crypto", symbol="X", volatilityHour=0.06).volatilityHour == 0.06
print("volatility contract OK - 6%/hour remains 0.06")

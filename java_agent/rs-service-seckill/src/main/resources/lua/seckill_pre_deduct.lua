local stockKey = KEYS[1]
local userKey = KEYS[2]
local quantity = tonumber(ARGV[1])
local requestId = ARGV[2]

if redis.call('EXISTS', userKey) == 1 then
    return 2
end

local stock = tonumber(redis.call('GET', stockKey) or '0')
if stock < quantity then
    return 0
end

redis.call('DECRBY', stockKey, quantity)
redis.call('SET', userKey, requestId, 'EX', 1800)
return 1

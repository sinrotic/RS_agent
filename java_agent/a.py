def run(nums,k):
    s_dic = {0:1}
    s = 0
    res = 0
    for i in range(len(nums)):
        s += nums[i]
        if s-k in s_dic.keys():
            res += 1
        s_dic[s] = s_dic.get(s,0) + 1
    return res
nums = [1,1,1]
k = 2
run(nums,k)
    

// This source code is subject to the terms of the Mozilla Public License 2.0 at https://mozilla.org/MPL/2.0/
// (c) LonesomeTheBlue

//@version=4
study("Linear Regression Channel", overlay = true, max_bars_back = 1000, max_lines_count = 300)
src = input(defval = close, title = "Source")
len = input(defval = 100, title = "Length", minval = 10)
devlen = input(defval = 2., title = "Deviation", minval = 0.1, step = 0.1)
extendit = input(defval = true, title = "Extend Lines")
showfibo = input(defval = false, title = "Show Fibonacci Levels")
showbroken = input(defval = true, title = "Show Broken Channel")
widt = input(defval = 2, title = "Line Width")

get_channel(src, len)=>
    mid = sum(src, len) / len
    slope = linreg(src, len, 0) - linreg(src, len, 1)
    intercept = mid - slope * floor(len / 2) + ((1 - (len % 2)) / 2) * slope
    endy = intercept + slope * (len - 1)
    dev = 0.0
    for x = 0 to len - 1
        dev := dev + pow(src[x] - (slope * (len - x) + intercept), 2)
    dev := sqrt(dev/len)
    [intercept, endy, dev, slope]

[y1_, y2_, dev, slope] = get_channel(src, len)

outofchannel = (slope > 0 and close < y2_ - dev * devlen) ? 0 : (slope < 0 and close > y2_ + dev * devlen) ? 2 : -1

trendisup = sign(slope) != sign(slope[1]) and slope > 0
trendisdown = sign(slope) != sign(slope[1]) and slope < 0

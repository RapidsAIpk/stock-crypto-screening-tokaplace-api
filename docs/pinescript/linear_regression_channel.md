//@version=3
study("Linear Regression Channel [jwammo12]",shorttitle="Lin Reg [jwammo12]",overlay=true)
len = input(100,title="Length")
dev = input(2.0, title="Deviations")
src = input(close)

lrc = linreg(src, len, 0)
lrc1 = linreg(src,len,1)
lrSlope = (lrc-lrc1)

lrIntercept = lrc - n*lrSlope

deviationSum = 0.0
for i=0 to len-1
    deviationSum:= deviationSum + pow(src[i]-(lrSlope*(n-i)+lrIntercept), 2)
    
deviation = sqrt(deviationSum/(len))

c = -deviation*dev + lrc
d = deviation*dev +lrc

Mid =plot(lrc, color=red)

Lower =plot(c,color=blue)
Upper = plot(d,color=blue)
fill(Upper, Mid, blue, 75)
fill(Lower,Mid, red, 75)
# Strict bare IPv6 parser; expanded lower-case output makes interface equality
# independent of compression/leading zeros. No dotted tails, zones or prefixes.
function hexword(s, n,i,c) {
  n=0
  for(i=1;i<=length(s);i++) { c=index("0123456789abcdef",substr(s,i,1))-1; if(c<0)return -1; n=n*16+c }
  return n
}
function global6() {
  if(w[1]<8192 || w[1]>16383)return 0
  if(w[1]==8193 && (w[2]<=511 || w[2]==3512))return 0
  if(w[1]==8194 || w[1]==16382 || (w[1]==16383 && w[2]<4096))return 0
  return 1
}
BEGIN {
  s=tolower(value)
  if(s=="" || length(s)>39 || s !~ /^[0-9a-f:]+$/ || index(s,":::")>0)exit 1
  marker=index(s,"::")
  if(marker) {
    left=substr(s,1,marker-1);right=substr(s,marker+2)
    if(index(right,"::"))exit 1
    nl=(left=="" ? 0 : split(left,l,":"));nr=(right=="" ? 0 : split(right,r,":"))
    zero=8-nl-nr
    if(zero<1)exit 1
  } else {
    nl=split(s,l,":");nr=0;zero=0
    if(nl!=8)exit 1
  }
  k=0
  for(i=1;i<=nl;i++) { if(length(l[i])<1 || length(l[i])>4)exit 1; w[++k]=hexword(l[i]) }
  for(i=1;i<=zero;i++)w[++k]=0
  for(i=1;i<=nr;i++) { if(length(r[i])<1 || length(r[i])>4)exit 1; w[++k]=hexword(r[i]) }
  if(k!=8)exit 1
  if(role=="public" && !global6())exit 1
  if(role=="relay" && !global6() && !(w[1]>=64512 && w[1]<=65023))exit 1
  if(role!="public" && role!="relay" && role!="normalize")exit 1
  for(i=1;i<=8;i++)printf "%s%04x",(i==1 ? "" : ":"),w[i]
  printf "\n"
}

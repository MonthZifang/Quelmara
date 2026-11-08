#!/usr/bin/env python3
# Independent Python reference for every bench, emulating C int64 two's-complement
# wrap where the C overflows (unchecked). Compares against /tmp/c_checksums.json.
import json, math
CK = json.load(open("/tmp/c_checksums.json"))

MASK = (1 << 64) - 1
def W(x):
    x &= MASK
    return x - (1 << 64) if x >= (1 << 63) else x

def expect(idv, got):
    exp = CK.get(idv)
    ok = (str(got) == str(exp))
    status = "OK " if ok else "FAIL"
    print(f"{status} {idv}: got={got!r} exp={exp!r}")
    return ok

def b1():
    n=20000000; acc=0
    for i in range(n): acc += (i*7)%13
    return acc
def b2():
    n=5000000; acc=0.0
    for i in range(1,n+1): acc += 1.0/i
    return acc  # float
def b3():
    def fib(n):
        if n<2: return n
        return fib(n-1)+fib(n-2)
    return fib(30)
def b4():
    n=2000000; v=[i*3+1 for i in range(n)]
    s=sum(v); t=sum(v[i] for i in range(0,n,7))
    return s,t
def b5():
    n=500000; acc=0
    for i in range(n):
        buf=str(i); acc += len(buf); acc += int(buf)
    return acc
def b6():
    cap=1048576; mask=cap-1; n=300000
    kt=[0]*cap; vt=[0]*cap
    for i in range(1,n+1):
        k=i*3+1; h=(k*2654435761)&mask
        while kt[h]!=0: h=(h+1)&mask
        kt[h]=k; vt[h]=k*2
    s=0
    for i in range(1,n+1):
        k=i*3+1; h=(k*2654435761)&mask
        while kt[h]!=k: h=(h+1)&mask
        s+=vt[h]
    return s
def b7():
    n=200000; v=[0]*n; x=12345
    for i in range(n):
        x=(x*1103515245+12345)&2147483647; v[i]=x
    def qs(a,lo,hi):
        if lo>=hi: return
        p=a[hi]; i=lo
        for j in range(lo,hi):
            if a[j]<p:
                a[i],a[j]=a[j],a[i]; i+=1
        a[i],a[hi]=a[hi],a[i]
        qs(a,lo,i-1); qs(a,i+1,hi)
    qs(v,0,n-1)
    s=sum(x%1000 for x in v)
    return v[0],v[n-1],s
def b8_1():
    def work(n):
        acc=0
        for i in range(n): acc += (i*7)%13
        return acc
    return work(160000000)
def b8_4():
    def work(n):
        acc=0
        for i in range(n): acc += (i*7)%13
        return acc
    return work(40000000)*4
def b9():
    DOC = open("/root/Quelmara/Quelmara/bench/speed/c/b9_json.c").read()
    import re
    doc = re.search(r'DOC = "(.*?)";', DOC, re.S).group(1).replace('\\"','"').replace("\\\\","\\")
    DN=len(doc)
    def jws(s,p):
        while p<DN:
            c=s[p]
            if c in " \t\n\r": p+=1
            else: break
        return p
    def jstr(s,p):
        p=p+1
        while p<DN:
            if s[p]=='"': break
            p+=1
        return p+1
    def jnum(s,p):
        v=0; neg=0
        if p<DN and s[p]=='-': neg=1; p+=1
        while p<DN:
            c=s[p]
            if '0'<=c<='9': v=v*10+(ord(c)-48); p+=1
            else: break
        if neg: v=-v
        return v,p
    def jval(s,p0):
        p=jws(s,p0)
        if p>=DN: return 0,p
        c=s[p]
        if c=='{':
            q=jws(s,p+1); acc=0
            if q<DN and s[q]=='}': return 0,q+1
            while True:
                q=jws(s,q); q=jstr(s,q); q=jws(s,q); q+=1
                a,st=jval(s,q); acc+=a
                q=jws(s,st)
                if q<DN and s[q]==',': q+=1
                else: break
            return acc,q+1
        if c=='[':
            q=jws(s,p+1); acc=0
            if q<DN and s[q]==']': return 0,q+1
            while True:
                a,st=jval(s,q); acc+=a
                q=jws(s,st)
                if q<DN and s[q]==',': q+=1
                else: break
            return acc,q+1
        if c=='"': return 0,jstr(s,p)
        if c=='-' or '0'<=c<='9': return jnum(s,p)
        q2=p
        while q2<DN:
            d=s[q2]
            if 'a'<=d<='z': q2+=1
            else: break
        return 0,q2
    total=0
    for r in range(2000):
        total += jval(doc,0)[0]
    return total
def b10():
    def ack(m,n):
        if m==0: return n+1
        if n==0: return ack(m-1,1)
        return ack(m-1,ack(m,n-1))
    return ack(2,8)
def b11():
    def solve(col,n,r):
        if r==n: return 1
        cnt=0
        for c in range(n):
            ok=1
            for k in range(r):
                cc=col[k]
                if cc==c: ok=0
                d=cc-c
                if d==k-r or d==r-k: ok=0
            if ok:
                col[r]=c; cnt+=solve(col,n,r+1)
        return cnt
    n=8; col=[0]*8; total=0
    for rep in range(2000): total+=solve(col,n,0)
    return total
def b12():
    def gcd(a,b):
        while b: t=b; b=a%b; a=t
        return a
    n=30000000; s=0
    for i in range(1,n+1): s+=gcd(i,1000000-i)
    return s
def b13():
    def clen(n):
        c=0
        while n!=1:
            n = n//2 if n%2==0 else 3*n+1
            c+=1
        return c
    best=0; bn=0
    for i in range(1,300001):
        c=clen(i)
        if c>best: best=c; bn=i
    return best*10000000+bn
def b14():
    n=50000000; a=0; b=1
    for i in range(n):
        t=a+b; a=b; b=t%1000000007
    return a
def b15():
    n=200000000; s=0; x=1
    for i in range(n):
        x=W((x*31+i)|1)
        s=W(s+(x&1023))
    return s
def b16():
    n=20000000; s=0.0
    for i in range(n):
        d=2.0*i+1.0
        if i%2==0: s+=1.0/d
        else: s-=1.0/d
    return s*4.0  # float
def b17():
    n=80000; a=[0]*n; seed=12345
    for i in range(n):
        seed=(seed*1103515245+12345)%2147483648; a[i]=seed%100000
    for x in range(n):
        for y in range(n-1-x):
            if a[y]>a[y+1]: a[y],a[y+1]=a[y+1],a[y]
    chk=0
    for i in range(n): chk=(chk+a[i]*(i+1))%1000000007
    return chk
def b18():
    n=80000; a=[0]*n; seed=12345
    for i in range(n):
        seed=(seed*1103515245+12345)%2147483648; a[i]=seed%100000
    for x in range(1,n):
        key=a[x]; y=x-1
        while y>=0 and a[y]>key: a[y+1]=a[y]; y-=1
        a[y+1]=key
    chk=0
    for i in range(n): chk=(chk+a[i]*(i+1))%1000000007
    return chk
def b22():
    n=800; cap=800; wt=[0]*n; vl=[0]*n; seed=999
    for i in range(n):
        seed=(seed*1103515245+12345)%2147483648; wt[i]=seed%50+1
        seed=(seed*1103515245+12345)%2147483648; vl[i]=seed%100+1
    dp=[0]*(cap+1)
    for it in range(n):
        w=wt[it]; v=vl[it]
        for c in range(cap,w-1,-1):
            cand=dp[c-w]+v
            if cand>dp[c]: dp[c]=cand
    return dp[cap]
def b23():
    n=1500; prev=[0]*(n+1); cur=[0]*(n+1)
    for r in range(1,n+1):
        for c in range(1,n+1):
            av=(r*7+3)%4; bv=(c*11+5)%4
            if av==bv: cur[c]=prev[c-1]+1
            else: cur[c]=prev[c] if prev[c]>cur[c-1] else cur[c-1]
        for c in range(n+1): prev[c]=cur[c]
    return prev[n]
def b26():
    n=20000000; seed=42; best=0; cur=0
    for i in range(n):
        seed=(seed*1103515245+12345)%2147483648; v=(seed%201)-100
        cur+=v
        if cur<0: cur=0
        if cur>best: best=cur
    return best
def b27():
    n=10000000; c=[1]*(n+1); c[0]=0; c[1]=0
    for p in range(2,int(math.isqrt(n))+1):
        if c[p]:
            for q in range(p*p,n+1,p): c[q]=0
    return sum(c)
def b28():
    n=300; a=[0]*n*n; b=[0]*n*n; c=[0]*n*n; seed=7
    for i in range(n*n):
        seed=(seed*1103515245+12345)%2147483648; a[i]=seed%100
        seed=(seed*1103515245+12345)%2147483648; b[i]=seed%100
    for r in range(n):
        for k in range(n):
            av=a[r*n+k]
            for j in range(n): c[r*n+j]+=av*b[k*n+j]
    return sum(x%1000000007 for x in c)  # careful: C does running mod
def b28c():
    n=300; a=[0]*n*n; b=[0]*n*n; c=[0]*n*n; seed=7
    for i in range(n*n):
        seed=(seed*1103515245+12345)%2147483648; a[i]=seed%100
        seed=(seed*1103515245+12345)%2147483648; b[i]=seed%100
    chk=0
    for i in range(n*n): chk=(chk+c[i])%1000000007
    return chk  # placeholder; real b28 handled below
def b31():
    n=12500000; src=list(range(n)); dst=src[:]
    return dst[n-1]
def b32():
    n=1000000; buf=[i*2+1 for i in range(n)]
    return buf[n-1]
def b33():
    def init():
        s=0
        for i in range(1000): s+=i
        return s
    return init()*4
def b34():
    acc=0
    for i in range(20000000):
        acc += ((i ^ (i<<3)) & 0xFFFF) + ((i>>2) | (i<<5))
    return acc
def b35():
    acc=0
    for i in range(20000000):
        if (i&3)==0: acc+=1
        else: acc-=1
    return acc
def b36():
    def add3(a,b,c): return a+b+c
    acc=0
    for i in range(10000000): acc=add3(acc,i,1)
    return acc
def b37():
    n=10000; a=[0]*n; seed=42
    for i in range(n):
        seed=(seed*1103515245+12345)%2147483648; a[i]=seed%100000
    for r in range(100):
        for j in range(n-1):
            if a[j]>a[j+1]: a[j],a[j+1]=a[j+1],a[j]
    return a[0]
def b38():
    def is_prime(n):
        if n<2: return 0
        if n==2: return 1
        if n%2==0: return 0
        d=3
        while d*d<=n:
            if n%d==0: return 0
            d+=2
        return 1
    cnt=0
    for i in range(100000): cnt+=is_prime(i)
    return cnt
def b39():
    cap=1048576; keys=[0]*cap; vals=[0]*cap
    for j in range(500000):
        h=(j*2654435761)%cap; keys[h]=j; vals[h]=j*2
    found=0
    for k in range(500000):
        h=(k*2654435761)%cap
        if keys[h]==k: found+=1
    return found
def b40():
    def bs(a,n,t):
        lo=0; hi=n-1
        while lo<=hi:
            mid=(lo+hi)//2
            if a[mid]==t: return mid
            if a[mid]<t: lo=mid+1
            else: hi=mid-1
        return -1
    n=1000000; a=[i*2 for i in range(n)]; found=0
    for j in range(1000000):
        if bs(a,n,j*2)>=0: found+=1
    return found
def b42():
    n=500; sz=n*n; a=list(range(sz)); b=[0]*sz
    for r in range(n):
        for c in range(n): b[r*n+c]=a[c*n+r]
    return b[sz-1]
def b43():
    def gcd(a,b):
        while b: t=b; b=a%b; a=t
        return a
    acc=0
    for i in range(1,1000001): acc+=gcd(i,1000000-i+1)
    return acc
def b44():
    st=[0]*1000000; top=0
    for i in range(1000000):
        st[top]=i; top+=1
        if i%3==0 and top>0: st[top-1]+=1
    return st[top-1]
def b45():
    acc=0
    for n in range(1,1000001):
        s=0
        for k in range(10): s=W(s*n+k)
        acc=W(acc + (s % 1000003))
    return acc
def b46():
    acc=0
    for i in range(100000):
        s="hello world 12345"
        acc+=len(s)
    return acc
def b47():
    def pc(x):
        c=0
        while x: c+=x&1; x>>=1
        return c
    acc=0
    for i in range(10000000): acc+=pc(i)
    return acc
def b48():
    n=500; sz=n*n; a=list(range(sz)); total=0
    for r in range(n):
        s=0
        for c in range(n): s+=a[r*n+c]
        total+=s
    return total
def b49():
    n=100; sz=n*n; dist=[999999]*sz
    for k in range(n): dist[k*n+k]=0
    seed=7
    for e in range(300):
        seed=(seed*1103515245+12345)%2147483648; u=seed%n
        seed=(seed*1103515245+12345)%2147483648; v=seed%n
        seed=(seed*1103515245+12345)%2147483648; w=seed%100+1
        dist[u*n+v]=w
    for a in range(n):
        for b in range(n):
            for c in range(n):
                d1=dist[b*n+c]; d2=dist[b*n+a]+dist[a*n+c]
                if d2<d1: dist[b*n+c]=d2
    return dist[1]
def b50():
    def perm(arr,k,n,acc):
        if k==n:
            h=0
            for i in range(n): h=h*31+arr[i]
            return acc+(h%1000003)
        s=acc
        for i in range(k,n):
            arr[k],arr[i]=arr[i],arr[k]
            s=perm(arr,k+1,n,s)
            arr[k],arr[i]=arr[i],arr[k]
        return s
    a=list(range(1,11))
    return perm(a,0,10,0)
def b52():
    n=1000000; buf=[i*3+1 for i in range(n)]
    return sum(buf)
def b53():
    def work(start,end):
        s=0
        for i in range(start,end): s+=i*2+1
        return s
    n=10000000
    return work(0,n//4)+work(n//4,n//2)+work(n//2,3*n//4)+work(3*n//4,n)
def b54():
    def merge(a,lo,mid,hi,tmp):
        i=lo; j=mid; k=0
        while i<mid and j<hi:
            if a[i]<=a[j]: tmp[k]=a[i]; i+=1
            else: tmp[k]=a[j]; j+=1
            k+=1
        while i<mid: tmp[k]=a[i]; i+=1; k+=1
        while j<hi: tmp[k]=a[j]; j+=1; k+=1
        for x in range(k): a[lo+x]=tmp[x]
    def msort(a,lo,hi,tmp):
        if hi-lo<=1: return
        mid=(lo+hi)//2
        msort(a,lo,mid,tmp); msort(a,mid,hi,tmp); merge(a,lo,mid,hi,tmp)
    n=100000; a=[0]*n; tmp=[0]*n; seed=12345
    for i in range(n):
        seed=(seed*1103515245+12345)%2147483648; a[i]=seed%1000000
    msort(a,0,n,tmp)
    return a[0]
def b55():
    cap=262144; buckets=[0]*cap; cnt=0
    for j in range(200000):
        h=(j*2654435761)%cap; buckets[h]+=1; cnt+=1
    return cnt
def b56():
    n=2000000; flags=[1]*(n+1); flags[0]=flags[1]=0
    for p in range(2,int(math.isqrt(n))+1):
        if flags[p]:
            for q in range(p*p,n+1,p): flags[q]=0
    cnt=0
    for k in range(2,n+1):
        if flags[k]: cnt+=1
    return cnt
def b57():
    def pm(base,exp,mod):
        result=1; b=base%mod
        while exp>0:
            if exp%2==1: result=(result*b)%mod
            b=(b*b)%mod; exp//=2
        return result
    acc=0
    for i in range(1,1000001): acc=(acc+pm(i,i,1000003))%1000003
    return acc
def b58():
    def rs(n):
        if n<=0: return 0
        return n+rs(n-1)
    acc=0
    for i in range(1,101): acc+=rs(10000)
    return acc
def b59():
    n=500; sz=n*n; mat=[(i*7+3)%100 for i in range(sz)]; vec=[(j*13+1)%100 for j in range(n)]
    total=0
    for r in range(n):
        s=0
        for c in range(n): s+=mat[r*n+c]*vec[c]
        total+=s
    return total
def b60():
    def murmur(h,k):
        key=k
        key=W(key*-862048943)
        key=W((key<<13)|((key>>51)&0x1FFFFFFFFFFF))
        key=W(key*-862048943)
        h^=key
        h=W((h<<13)|((h>>51)&0x1FFFFFFFFFFF))
        return W(h*5+1)
    acc=0
    for i in range(1000000): acc=murmur(acc,i)
    return acc
def b61():
    n=1000000; a=list(range(n)); acc=0
    for j in range(10):
        for k in range(n): acc+=a[k]
    return acc
def b62():
    acc=0
    for i in range(5000000):
        if (i*7+3)%5<2: acc+=1
        else: acc-=1
    return acc
def b65():
    x=0; y=0; seed=12345
    for i in range(2000000):
        seed=(seed*1103515245+12345)%2147483648; d=seed%4
        if d==0: x+=1
        elif d==1: x-=1
        elif d==2: y+=1
        else: y-=1
    return x*1000000+y
def b66():
    def f(x): return (x*x+3*x+5)%1000003
    acc=0
    for i in range(1000000): acc=(acc+f(i))%1000003
    return acc
def b67():
    n=5000; a=[0]*n; seed=99
    for i in range(n):
        seed=(seed*1103515245+12345)%2147483648; a[i]=seed%100000
    swapped=1
    while swapped:
        swapped=0
        for j in range(n-1):
            if a[j]>a[j+1]: a[j],a[j+1]=a[j+1],a[j]; swapped=1
    return a[0]
def b68():
    n=256; sz=n*n; a=[i%2 for i in range(sz)]; b=[0]*sz
    for r in range(n):
        for c in range(n): b[r*n+c]=a[c*n+(n-1-r)]
    return b[0]
def b69():
    def fh(key,cap): return ((key*2654435761)%cap+cap)%cap
    cap=524288; tab=[0]*cap; cnt=0
    for j in range(500000):
        h=fh(j,cap); tab[h]+=1; cnt+=1
    return cnt
def b70():
    n=1000; a=[i*3+7 for i in range(n)]; found=0
    for j in range(1000000):
        target=(j*37+11)%3000
        for k in range(n):
            if a[k]==target: found+=1
    return found
def b71():
    acc=0
    for i in range(1,1000001): acc+=i*i
    return acc%1000003
def b72():
    n=10000; a=[0]*n; seed=777
    for i in range(n):
        seed=(seed*1103515245+12345)%2147483648; a[i]=seed%100000
    for x in range(1,n):
        key=a[x]; y=x-1
        while y>=0 and a[y]>key: a[y+1]=a[y]; y-=1
        a[y+1]=key
    return a[0]
def b73():
    n=1000; adj=[0]*(n*n); seed=55
    for e in range(5000):
        seed=(seed*1103515245+12345)%2147483648; u=seed%n
        seed=(seed*1103515245+12345)%2147483648; v=seed%n
        adj[u*n+v]=1
    visited=[0]*n; queue=[0]*n; front=0; back=0
    queue[back]=0; back+=1; visited[0]=1; cnt=0
    while front<back:
        u=queue[front]; front+=1; cnt+=1
        for v in range(n):
            if adj[u*n+v] and not visited[v]: visited[v]=1; queue[back]=v; back+=1
    return cnt
def b74():
    acc=0
    for n in range(1,5000001):
        s=0
        for k in range(5): s=W(s*n+k*3+1)
        acc=W(acc+(s%1000003))
    return acc%1000003
def b75():
    a0=1;a1=1;a2=1;a3=0; n=1000
    while n>0:
        if n%2==1:
            t=(a0*a1+a1*a3)%1000003; u=(a0*a2+a1*a3)%1000003
            v=(a2*a1+a3*a3)%1000003; w=(a2*a1+a3*a3)%1000003
            a0=t;a1=u;a2=v;a3=w
        b0=(a0*a0+a1*a2)%1000003; b1=(a0*a1+a1*a3)%1000003
        b2=(a2*a0+a3*a2)%1000003; b3=(a2*a1+a3*a3)%1000003
        a0=b0;a1=b1;a2=b2;a3=b3
        n//=2
    return a1
def b76():
    n=1000000; lines=[i*7+3 for i in range(n)]
    return sum(x%100 for x in lines)
def b77():
    def fib(n):
        if n<=1: return n
        return fib(n-1)+fib(n-2)
    return fib(25)
def b78():
    def ds(n):
        s=0
        while n>0: s+=n%10; n//=10
        return s
    acc=0
    for i in range(1000000): acc+=ds(i)
    return acc
def b79():
    keys=[0]*50000; n=0; seed=42
    for i in range(50000):
        seed=(seed*1103515245+12345)%2147483648; key=seed%100000
        pos=n
        for j in range(n):
            if keys[j]>key: pos=j; break
        for k in range(n,pos,-1): keys[k]=keys[k-1]
        keys[pos]=key; n+=1
    return keys[0]
def b81():
    def bitrev(x):
        v=x; r=0
        for i in range(32):
            r=(r<<1)|(v&1); v>>=1
        return r
    acc=0
    for j in range(1000000): acc^=bitrev(j)
    return acc
def b82():
    n=5000000; a=[i*2+1 for i in range(n)]
    return a[n-1]
def b83():
    seed=12345; acc=0
    for i in range(10000000):
        seed=(seed*1103515245+12345)%2147483648; acc+=seed%100
    return acc
def b84():
    n=1000000; keys=list(range(n)); vals=[i*2 for i in range(n)]
    for j in range(n):
        k=keys[j]; v=vals[j]; keys[j]=v; vals[j]=k
    return keys[0]+vals[0]
def b85():
    def pc(x):
        c=0
        while x: c+=x&1; x>>=1
        return c
    acc=0
    for i in range(5000000): acc+=pc(i)
    return acc
def b86():
    n=1000; sz=n*n; a=[(i*7+3)%100 for i in range(sz)]
    return sum(a[r*n+r] for r in range(n))
def b87():
    n=12500000; src=[i*7+1 for i in range(n)]; dst=src[:]
    return dst[0]+dst[6250000]+dst[n-1]

# b28 special: emulate running mod exactly like C
def b28_real():
    n=300; a=[0]*n*n; b=[0]*n*n; c=[0]*n*n; seed=7
    for i in range(n*n):
        seed=(seed*1103515245+12345)%2147483648; a[i]=seed%100
        seed=(seed*1103515245+12345)%2147483648; b[i]=seed%100
    for r in range(n):
        for k in range(n):
            av=a[r*n+k]
            for j in range(n):
                c[r*n+j]+=av*b[k*n+j]
    chk=0
    for i in range(n*n): chk=(chk+c[i])%1000000007
    return chk

tests = [
 ("b1_int", b1()),
 ("b2_float", "%.6f"%b2()),
 ("b3_recursion", b3()),
 ("b4_array", "\n".join(map(str,b4()))),
 ("b5_string", b5()),
 ("b6_hash", b6()),
 ("b7_sort", "\n".join(map(str,b7()))),
 ("b8_threads1", b8_1()),
 ("b8_threads4", b8_4()),
 ("b9_json", b9()),
 ("b10_ackermann", b10()),
 ("b11_nqueens", b11()),
 ("b12_gcd", b12()),
 ("b13_collatz", b13()),
 ("b14_fibiter", b14()),
 ("b15_loopsum", b15()),
 ("b16_leibniz", "%.6f"%b16()),
 ("b17_bubble", b17()),
 ("b18_insertion", b18()),
 ("b22_knapsack", b22()),
 ("b23_lcs", b23()),
 ("b26_maxsub", b26()),
 ("b27_sieve", b27()),
 ("b28_matrix", b28_real()),
 ("b31_memcpy", b31()),
 ("b32_io_write", b32()),
 ("b33_startup", b33()),
 ("b34_bitops", b34()),
 ("b35_branch", b35()),
 ("b36_call", b36()),
 ("b37_swap", b37()),
 ("b38_prime", b38()),
 ("b39_hash_open", b39()),
 ("b40_binary_search", b40()),
 ("b42_matrix_transpose", b42()),
 ("b43_gcd_lcm", b43()),
 ("b44_stack_sim", b44()),
 ("b45_accumulate", b45()),
 ("b46_strcat", b46()),
 ("b47_bitcount", b47()),
 ("b48_sum_matrix", b48()),
 ("b49_floyd", b49()),
 ("b50_permute", b50()),
 ("b52_io_scan", b52()),
 ("b53_thread_sim", b53()),
 ("b54_merge_sort", b54()),
 ("b55_hash_chain", b55()),
 ("b56_sieve_opt", b56()),
 ("b57_pow_mod", b57()),
 ("b58_rec_sum", b58()),
 ("b59_mat_vec", b59()),
 ("b60_murmur", b60()),
 ("b61_cache_scan", b61()),
 ("b62_pred_branch", b62()),
 ("b65_random_walk", b65()),
 ("b66_integrate", b66()),
 ("b67_bubble_opt", b67()),
 ("b68_bit_matrix", b68()),
 ("b69_hash_fib", b69()),
 ("b70_lin_search", b70()),
 ("b71_sum_squares", b71()),
 ("b72_sort_insert", b72()),
 ("b73_graph_bfs", b73()),
 ("b74_accum_poly", b74()),
 ("b75_fib_matrix", b75()),
 ("b76_io_line", b76()),
 ("b77_rec_fib", b77()),
 ("b78_sum_digits", b78()),
 ("b79_binary_tree", b79()),
 ("b81_bit_reverse", b81()),
 ("b82_array_fill", b82()),
 ("b83_lcg_random", b83()),
 ("b84_pair_swap", b84()),
 ("b85_count_ones", b85()),
 ("b86_matrix_diag", b86()),
 ("b87_memcopy_big", b87()),
]

allok=True
for idv, got in tests:
    if not expect(idv, got): allok=False
print("\nALL OK" if allok else "\nSOME FAILED")

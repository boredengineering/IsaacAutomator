#!/usr/bin/env python3
"""Offline bounded GR00T consumer tests; never import or run the native engine."""
import ast
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
COMMIT = '51d4c89f72fda44cbf77285c6a8114b52676b8a1'
REPOSITORY = 'https://github.com/NVIDIA/Isaac-GR00T.git'


def consumer():
    assert importlib.util.find_spec('src.python.gr00t_serving'), 'bounded serving consumer missing'
    return importlib.import_module('src.python.gr00t_serving')


def configuration():
    return {'source': {'mode': 'git', 'repository': REPOSITORY, 'ref': 'reviewed-label',
                       'revision': COMMIT},
            'serving': {'enabled': True, 'bind': '127.0.0.1', 'port': 5561,
                        'embodiment': 'NEW_EMBODIMENT',
                        'model': {'repository': 'nvidia/GR00T-N1.7-3B', 'ref': 'main',
                                  'revision': None}},
            'cache_dir': '/tmp/explicit-model-cache'}


# Exact public Apache-2.0 upstream source text, preserved for offline hash/AST
# tests only; never executed. Provenance: raw.githubusercontent.com/NVIDIA/
# Isaac-GR00T/51d4c89f72fda44cbf77285c6a8114b52676b8a1/{path}.
# Retrieved in /tmp/isaac-gr00t-source-evidence.json (C08); base85/zlib avoids
# importing upstream's Torch/GPU dependencies. Copyright NVIDIA 2026.
import base64
import zlib
REFERENCE = json.loads(zlib.decompress(base64.b85decode(
    'c%1Eh4Raeevfy9A$yF!PMbfgJynDwSUp-lp9o^cJSCW&rE2*d<35pYuGu)Y>WUWsB{rUsI02mBEWIM^$GgB3d9H0R-8r_Zlnuo3H'
    'Y-gu<A#bDUi)@kf>1#ii*{#ev^ZTu?*m@>TKkolm`)xdxd+Gc>i?1ienfzRIh50HP!=`w(^XlKk(JzPlhr43$_~hg9$?n<V@saqS'
    'V)yOa!}o`~X9uSpu{)g#>XVC1(m12eMWV)d9}i`c%l6?&CPh4sW!4qD^JqAc?N^;0Xof9Sqmfu7BbkX}B2^pxq$PflSstf}fKH-;'
    '4KB9Svx}|fPYC2bU5Ht9FOswni(CSfI2U7BqL815a$bly5yNygpT<!#l;SQfCNz=)LsR~nf{_l22%1OGVGiHMc0&;rYTA>cn0H^i'
    'xVyXSL^Rz_nq9w`a<lx!`@_A1qtgRxou87a%n?ifSi~7DcW^JFIZS964Pctn=uV`Wh^{jU&x#Z$e3!*VoLsj=o{o#VD3b_g6z4@2'
    '4;F=kF+Dw4wcP-47A1hK-BWRRda)(m?4BN;wh+v(hi5+@e>xMt?w*|N9-SQ?oQmTU*yp4DL)>Nf_Ezj3{Z0Jk@Mym!B;X51lAq@p'
    't^p<*BQEt`OX*Bvobsgdxg5f-4`Ff1^&+~K;yML7Okho7F0)yj<F4i~#Swy;#<RGH3i_$CG8pJ08E5HCjG`hMPNN*KjI&6yqWtM1'
    'QNQp%(|BNh`7KWq^Cis{uz6HWpp^#n5x$y6`F(B%rE}E5aXNA~NJsGuD7s%n*Jcg}=I68My4tI_pO^FfkdC5hT-@)a$vAc!&r_g?'
    '`wpL5{-S%m!{0vAPoXZEoKK^Bug?knSl@{`Lw^W+nG^;K^z4)#8Eh2yS&HbmNcIoj?tXfI*8gz4fAGG4dT{c~!AT$3!<p!bAK}BT'
    'Msh6r(=;0O5%c|-T5^9#Yt9?|Zyz_HOL%XJ_J08J4vTZ3-<F4?%kD)Y;B&Es|GfvWa6bR<DX=3t<ad)4=nk0P0+0*`#p?}?<a9*9'
    'b0Q=JwM%4^%VIkhS64GxL@)FtJ2>U5D?CjR^cs(4hUjTvhc@6dT@+1`!<nB&NW9RFK_d5whRAQ=?7@KnMzwgg^YRBVPh;qxFNPE3'
    'P8ooOh5{I}U^KvK&kG5Q0&X*v1)h2&eujE=<*ugj{P}GYX17Ry@7#ziijgmg0j~S%>I?|&Aj{J1>Z)VojQ=Lam(FEk<G%$>GT@{l'
    '0-mW5jh_s7QjZQ!2RE`YZt}AtySH1(Vv!}{;ifAB^CV_)(-ODH&;Vd3F61n4G#?p&;?8E$I0g94nFKEH7u;HE(I_9`XMC~sU@hel'
    '_l&l|Cjlguu8_c~nNGxPkr!f;0$q45HLk27h<<V)068t9ew+X$$-E^DQQydW_}b}onjMF(s#Jyhk5m;Hq$D&Zt)GB9<+-904MY=6'
    'Lw2q^fT{@iFo>Je<Ci--FY*-ruTB_rYHG6T*rUOgAR7QI^FjSji+j>Pf=@nU!#Q{S(;_1#O*;!ZMxuySygS+1IfEf-5g=rh)}hId'
    '0X<_jCKQ`e+<>3K8s$`R1mFSU|B0hCkwAj@k3A1$7bqifRO%!EVZ$3fWh0QT!y?V@-GN=U%>(oRULx=M<ui>a?pyM70ewUxiDnXo'
    '9}!SX3}KhsfMSqOAgFI8Z2rk2;WO55PvmrtlgvRn-X!T=f-rIq9V2-Qq*TskxEMw59QLUN0s>rHD+X!iA(nZ45VMLRH^r^$#yic>'
    'i!AyrgkF!oKVcVb@-`#}%-!3@&vLlHXZ=Z<#s5r`uE0&NAB3@Cx(U@yj20OZt|3?0JFS`BO=JQas8-*`r65~DOf+nP+N{tvpBxwW'
    'AexGDgLgXgpS#CDLlY5=Mx<OB?TO{DGXhFtUT{y;ieY#8Ai9&qYyh)b1{hVwA%GsF=@ej}WeW$3zfL46fUsLK0XTTNsRztuz9>it'
    'f>6Xi;cUbs+C6s!;CuZ%o+<sLf0u#si}wLF;@fDN*A2-EJq#JoG<B=)<q)iJ%s_EhlCA5ov8Li<iZ{B<0ETz8H&CVWbb2cr!PZI$'
    '&VhW2#>LiY5oIK=YuH~0h{WjvoL&f*vvkEnaHz*n*AI03`F!baCFcxw*;iafH)pOBZ2B`%t8R$28*KKG2vIjfvgBs^Anau_DkRZG'
    'jtH^|kDA0|QJK4z-FSvA4d5AbckEKKKWZ;O!(AsYTZVvkX#5<RGVIn1QgdKdI8K^(s0D**RJt~;NtCJxUYw88;%y3d6xK)pBju)q'
    '_C$<Q$xEZ53_|%x6G8WE_1@EQT%za&Nu}j>DF^RWrsFkbV(2-f;Wgp2uAA^TtBG2ToR;{v1y0SjmW?Ys9ea4KOZ?ZWg3LSGZ3C`t'
    'fy>rl?!HdO03DVu61bkDPBu?j<|8wf*UYD)(JfgQ<UGy++j+C&Lu{_M{QuJvJDab499}%>xdUlt{1e>5i<05^gFl8QUH;(T<GS@%'
    'wvbSER~}LtYN!Q2cB>xU85>IgHQml;RK*n*<8l01^iU>)s(i84ts?Z9I0Jrz+BaP?W4xNoLHS_=%`igKm%N4p4L4|S290J2T!gj`'
    'eap_{k!(v)`G>_%f+P+rC}V(|1E<T<#Wm_jAwVGWci$hL{jI-ueDwD4-6`zvG`;Ioo96e5$Dz1PMh(~}`{oDF@WRmy%+^>?I{X)|'
    'a50rmZ&>*((ACHZyr%=QJmt>F4NqX{kHtp<dqsAf&~EvZ2_&+n{h=~`?o%Fq);NLqfn|S6^2Ho+R$V(PVY8@kQJ@z1*b$#{rZ>>k'
    ')IzI+ILGmsc#Ca~Ap!2F@I6WOaJ0OZn5OBCSj_q6heDL;7L<7VR8}w;X2X^hNj0n(#tZ;u@AAmiUO~;)`CU5KvIy&A9lDKGPy3py'
    '*=%c%QZZP>(*mx2p{=z<HQg9P`==mnhgH4~-Z3AyMT1t=t7}D1AGhJgxnzjl+bEurbs2A-Kyx|KWTS#xG+#8D&BvwCK29Y_OgP->'
    'EpRRnp?dvoo+69V1{vj;CY#H^ksMy+Y&?LiL3Gj0*%r4IS%jaE@?>}NcF$HtjFw~lR@Iywvg!Fhc<n0!)aYmagC{Cg4l}A!>ed0<'
    '<}EcEu<z(!Mg!oj8#$W#?tDJI4_vMA2%)kA%{_&^<|bE8aszYrX*}ai`&C`&lECH$TQ>NySqagOZMkmvkb3-&g=4(l=ncTXTXvVs'
    'Ji@=#BeIe5J;qwFYY?T)<;!2TNNi0&Sv&tC?+0m=jSfL|%(BJ2@H*?O<;6vEI$5wac!UNd_ezQX!LIcC$TIqUmXG~D-humlBO(=Z'
    '>X8AzGn~c^=U%L=H|4z<e%WdX<ws<Uy>Pq)-`$Ac-H88P+=$~vGAz<`YB?5D&!fmH)%~1|iTq$Uxo?R*P~&k+E=sTCEWbvNjsLx$'
    'EM`C<z*uI<+&nZtTEG2s_K%Q9a$VmdH3pG1HI0juwPQGOG4%SUo-lRlxcvGJ2o&u|#Q)e=@FBlGRh<n>WUHLJy4*D4Qxk~^a6oZ&'
    '1!zj|`tx{rGnGBE0$yE-0UB4L?A|!*4$;kl+7H`>;e5)ji$C(>eT1(vySjRDb@hq7WB3II%+M5dZw!%HTZ=;IGm_(IF)gT5IzZz#'
    '2<-F*`aK`WNt}$HBLT&k01m7ja<EYynG8YXQaAiMlKfRPuC5H(;QgwAbvL+iOAIH#6M8s>{y1q~T{YF6?Q9YOJ;;d2SnxF3BivYl'
    'h{%ASkdcCrnDeoBry&|>)`}P$9Gz=g+(R<zk~Oy_Zesj<`*@oiRgchP9^K;w2_cV}TU=f7Mv%WR$BnqRm#o*=MAX0-@;UA!-YwA4'
    '1Um^(ZsSO`M*I&9e%M<H-<4Rxi!jQ+Tbam?_?3=+MnJ_VL&FMm<Nbwcuuli{6kH?WP*1C$M`PK4Q26BuKBC+8<^O(#=c!ZkXb3t{'
    'Is?$@BFp9U7TtMyS~^`}DvLatqSFN>K$aJtH<iErXO0v(oXKL6j<ic>jOS`_U&x$1#$99x<lUy<EMc!m4}^1-Vw{83;bpp1<h9_3'
    'eO{QQbSVF<LMHDD&8wxy@2P*AD^`VE!C4pmO)G;HTI;foQE+Xpx)WL{?^ex9`Jq~AMPm-ES<#+awKcn*^>+*1)69WZA;R8`27u7>'
    '#Or0#v0R@Z8Oh**&IO+#QJ!LPmoBCwxJ1T<KFJKG?jZ9vs53hPHkda6b`uY`Om5{gokRP(Nj#j`&~i{{5<E?rY|8|Beoitn$_8<f'
    '0o!fUWb#Eej?ndpya}I!)V__=MefcFW}ip5vH?t`C92%KNsNY!^{A!9I4&%E5RIf|uL3<b&WVYDUd1Q{xC&Fg9UdA(iw<G4gV<oz'
    '_c&-4;v16*FsQ%U(^k=S6rEgzfgm4l<dbMFdk;7T`tz~*)3S@MD+hUp<K#BIk$U4mV}{KlaZKuBG6edS%U}X5I1fX?GgEYw%VY%e'
    'Uv+2JXTwmPO~Lg4^~j%3;WF|MY$_Uy{q3AZ8OUj16o^qY^WZH;VY^RS23}`c=J6o-+_zz(1&9C#XhI7<d&ns7Cuj$D#?e0p4WwgR'
    'fYw-+2;u8lm+*73^&y&~i4X*-rZ+W6SK|qFXS6SYYA&{Ug4=?W;N-fFWCGJyWB^n^u|09xd4t^i@VKD{Yz9xWYkXY7-t@d3Hpeuh'
    '4gng_T~^{LA9(F33ew`x##Ce}X&5AR;Lwm$aF7CPp<mj30Vv_Y{iV$mJ`x<DLmCprXQ4U>*Y-s*K|LxN!Dt*6)WECXZy;H0Na&*m'
    '-3+6vfCHocljBKswXBy*R4m7t8713n{m%<IC&mi5nv69k#VkOX1?8xHo43h5PI$$I<Q*H5%UO0hKXm>bI-;RKIZRO{hP^o-Y$v1b'
    'OZ?9BcU2t*2Ed1K-$M;90#Td5O?;H%Orv43fSp2Vfx%Pu9s$D|MR3;vQnW!i;#vm`u!x~;1c-t}3QS0A`e=~`B+%V99XqQ`=CCT#'
    ';a`ZDOaN$eq!kX4aVB)vTP{pOd?y+8Vb3il00$l@$l?I}-9P-e%hjIvtJ{}<3GgM=9jVd4f_pkbIYtolk3U;Fv+HpZSC*+Wx9p6H'
    '2JdQnAR~;5St8Ibwn$T`Fotqx(M`r%PPY_ScUxaJRmIDCvdK|{vHJ>%<ldJnE`Jr=h$6>rNhUU>k&&QKj;Y|Cn&$CXSttCuYB`Rs'
    '8(0pqt96Lo9#Q}HOdPUR$_s#0f(ACymo>PsZG52QP0I$x)M-Vs@|Z}5c-x<j+k*_Wo`mLS9oGo}Hb!=%40yC1-T*u{&XVwxW@4~e'
    '^FV8(S8OsweJ9uPA6T)sT_CRj2Z{V#G#WP?LrW~eqO_J6Sl^lm_ePBiqMLNF3g<zvU&9SnYAGJ+EK^pNIl~NXDZ=WI#O`U2RVL?I'
    '<EB|60=caATCLzI_;D1zbLe<kL5+2YRO^<y-!4@k)nA%jRZ$*-3!2Gts3zt*H`-Y6I9CF$tF2vD6AJe|NJbPn`!finsiDM)`eqq2'
    '864T2^F9Usc>#l^S<rUGI95UadpD^B%JDTbpTp)Z=D;xiF0=H*UqMj;^^XG#rx<C$VaG8r`57`6oDS$wTKeySk`|3d%DMw`h*y@Q'
    'AVPH$yIh%=4gJ^;l-I7YH>jIP95}%UpT;b2qE0%TVzL2gfOEcbQE=?NipfTXdUX>|r&pjl-840@@pO?-&`ewM$AKizPL|H+azyv^'
    'DaKXC6jy@YRvlSQ_Sboq&gO7?R+H`Ty+1xZ=)XTadUtTr|8NSM@N#EorwlAc&rqDiMZa&I<6KV1j+YC!scYGGJ?~f<xcVG8j_V%N'
    'fvA}CVLgiGalb%5ulpjm(eAUZJC%;{@y(TG*?EdHfM@tmrC(N1ugrg<Bhu|4R`ak=dpC09P0dqOVSwYp(|^wX(b?l~_K~JmiXwYX'
    'AN6YkJDwbT4EN~_K-<H(m|}=Np9hMr>^_vylkQv%_1ZC3-eJ9jc|1INJ<SflL-V(PapN<<<c0Xsqv26e_CO!A{<#5ZG^a~vOU;;h'
    'Mt@G;CYMu~>*Gq0cyvmT_)X<6J{=_J<9$#~V-}kh;dRO<>%c)_R`?+3$2EF;>I{zTg%&s`3_s8YF2GsC8m?8_RZOGVU=($M9-1DU'
    '5Z>HS1B+=`7^i{lGs_(Ev`G2hiWv#hG@W<Ez7B9@#--x5`J}uM`e3PSC^Q*dUC~i&G%-!dk_>@!td43qMea#+L)){b%`mhRYaVpR'
    'v?a;kL9pn9D-K6;Hct!mZ2J=d@ojGb;$CqO#5eMnu$o=VbpkA@vQG0<^BI2%`~YX*DS0qm)u}#)vKp#Tj@4nrvbgK<)IBNVhsv>6'
    '{DA&}LljhMa?4;`vRHpr>PdK6y4$Af(wht?apvo0YtP*ls1jXPAW{8;fgBaR_vkA}H`N$<tCqhUG9b~DZVQ5@Hp7&=W&=c{Pz1w~'
    '0&**zd_pw9lC?NVfVPJi&liCrB6HgeV!|*lU=52`|Lf&zou7iO?=>t|tB?diw|Ovf7X*`$w2ug3tEyCD0}nr+N#Wp41q}Dm+(3V|'
    'L@}s{f5ihF7?uzz&o~Oe${8=epJE(=5@bqoWqpz-iUHgCVmL(O(hU9=UE96~A6R+k$2<8V$4mXiR(ivx8P%VERQSaBaz4fvTaWf)'
    's$zgKgAqHV9<{1^wlC%!9lOem%kM^}M{sexD+RhrvC`>y7I)gsu5;fgMl-{>XHIrw1A&I+MHrj8V|$Hva`&N=o;KhPwb_9r?OR9R'
    '+Yk|Vlh_CBW56T>S>xz7Dg}vx8|sncsZ{5<I#ixKeX60L`<vjBsLFAYtXZi&RaX&K*4W((`?h4ieo;_3R_WuRV4W>aRD>>pTe2i%'
    '_pZ8ElQzNhjO2rS<tSAH=@6m{<?Er9W5j5XTTOJdxnnxizDO#J5wqH~uB@0JfW^PkdC|uZBRJ-$HNW3IJ?kGF?SDKzJUVLzxR`a;'
    'h<%k;Le0ByELV|MS1L=+t|d0q8TaO$$>D7%u3w=GgO(jzr{ykJ03Gj%{yeh?f%ZlDOW?kT49mLZR{JUgAQQJom8w(7(10I%W#~Cv'
    ';+1ljWnvqEK}s|eF)RF(M2mtVUFE1N4ilP9N!Gv^1E|AK&Ce*h<76R2C^O8X=h3Quz^vL<`-7+l^chfONKGnNukhq5mNJU^=PX~{'
    '7Zh>*=VQ(Inw9k`>`DK186vlwV@7IrOabkve;d!AyEsBdiTHtQLJjK4Ldif}E*Nf(A<C6e1E2#xRfw>L)OgMQe0>d$iU)+$IL$)1'
    '#6YYAX>o_D=_iB%6&{yGLph+3y*j9-Nry8#Km!^!LWo^=srISDY#rI8ePVz$UII#S)OWUkO{X;1v;tP0u*Jsa8`aoqeHo<)Y6_j^'
    'h-nIyE&=w;U*W)MMvNUQ?VAwyDCW3PE=JF5Jp-4!+Gz@E2w9WXv}G0XOr{ICZRfhd%O7`kcGk3Z(R|#*YWwQ#Xu}H(X>WGSid1$0'
    '|5GsyeFZbtQ*3J`IxwExd|A)@<gS30sf=c>a%DdW+aC_01)m#1g$d&FyLFo)q8%<WuBgF9Rq~)(xQ0dVuQe9E+~_jgaPOD1!w(0?'
    'EgxU&bw54Y->5rGHIc)@GAY(v-?khSyH_huOAX~RAXY$s4;lVenB?$d>7V5T#k+CU#O^wO|L|90&!NFxYT?`VkTcBH-l0<fy=53M'
    'B4_g=ID?8IX|<`V{Qeib$T;_?x|TtFX{%-pzAWRG+tFogmU2OtM~?r)3x}I*yYvpJxKA}~(_aYQNHHAQ=tya@!A-K9>YBGnUJN!a'
    'Z*(RJpr+5Vi=vtKW;aFW9*5?2TdnMhQm3;oV%|KelLUz8TKB?xC;e4_m8*qd-Nr6O-DM0vHRpIOWs5Hk-Z5V9QdBwDyVp_dFXx#!'
    'W7ei^P{3dv)8!p1X%r#O*9cU5q-fkll*vLw5&0n52Ui*$5{cKvD9gAqPsuXkLfhSlV^ALVFiL!Qh$0c;>|59vuf=WF`&Dl;X=GH}'
    'C+A=$eG?o<aP1s*R&p|LlM%Q>69(ly^z|Q{oE)E2VqAGjCyNB7h0Y07cV*rI@gcgQXkIDqBvnVVt2PbO3}fqcww)>3<XHRid5Rf1'
    '8{TkT@3)4c;#27UZggF$4yGEcUf|eWA?WeC@A)?UvVHj&vRCR>U*b%#NcGR;O8A4F1v}pz17XL&x3rY^G2=Jni+BS}2un*)n(ZD{'
    'l%Ojr=F4!Wt1HUD8DmtXse}b9m}BI5X2Z%Si-M9**{8u(Alg%4u2T}~IVL;-yT_=~bU|5CsDyFqpslz*6O-r`gVoUjoB~b|>Q8jM'
    '$!w4A4cJDEy@kERGY{%UUX0*CTb#5`J=N%0a}z5YSlWszI#)VCrbvlrwkIBRr%QN9&~yJmsP+l*mtrxW%5xuz`~A|PAH#b?dZn`{'
    '-_Z@4i#2ytUaYTpwAAG33IAznHC6UWb2ogP^l+WIfQDGnptM01mE0u11NK0*ufelwVc1XFbX_F5)NYZrkm=P4#RlQ?R?)$Y`~D%g'
    'bZ1%tAG_;~T2`fW)kJC>_^a;*81&q?HnFjiLPJ80CF)UHn5;@U3I+TD@AU`Nj5aQNc7&=7L2i9zx8Ouh3O|l>%1l=E;${?!oRt7r'
    'b7G5@_I>1w0oj1ux|LN-r~}JL;4j}|{S5h!U3w)a-!7@}JthBpO8&ogN<OR0TpISHNjtYwzB%ku7wg16XLNc<AJL^vbdm|W&r}&y'
    'mEvy~tL0&+U<w*7+IHzZwwpV>sV`R@G!rnr{IVonq5hy=NSHAFK}>amh&HJLU^$CCo-L-lLYdsgS(@OI^9!qbW__XZaP0xB;y|c~'
    '0O(#r(>IHfoFch1Qxjl!QKVGPutk4<WH)4*ZBPsS?cveE*{7p}{_)ZKzxB^{-<`I^$K%tpvy<J!BlUeny>!w>G5s`m>JOBYSzZKz'
    'Z=+|VQoAx5c+UIX(?ZVo$pW*g)<H{D>eHy&=5TB77ipgoY8s!rT=jvzbs5K;pz7J#^o4S`0LBM8^gZV=!I)@<7*ErPh(kqg!1+jV'
    'XA+9($SH!T$QHu_FY_v{;~KyuJg_mzdFHs!=#VugwGu*u2VniPMM_)?SwM<B!P5WKs?MSeG#6f+N<Bp)4^LW8<%A<}tl8|llb};k'
    'vv7qQ=9>i%PXlY{zebto)dyMMu7RdwQKoWS;Gu|hw3K~Wca0XGTWT-Q2nJg%_?I~E>v8(5*nJLM{62Szv_VtuF*$IHXMzJx2=nb}'
    'e4`Vz;5t=+B+Do1qVpyyhLg84A~Y%OgN%}xO)<d*a4mJELfB<E-6gQW1-1%0(cStpYX8*RO*FG=xx4gzt4Q0e=l<DLbH^1ik;K<Y'
    'n#tO!AdLk^JYO~(k9DbGx&^TmnyrJ0wW+jR>JJcy2slUE98QArJj<F4{?R-_H!k^-uqKv~Zv+Pz3`dmAStCLcE9)JDu0M-F8ye=F'
    'dV*4=!^6q#YBAIX<BBo6ywQHy1R6rT>HBREqL)*m@k&n>>TK|~r`4`JTXnQvsM7CQKq^|2)DzCwlLWNt!*Kz*Hq5t+w2k)FG7DrL'
    '&w*Twp8m39!eX@D-nxb;!_g~Hz*!<dBl|Hk6*OjmuAcz=0G_V{YEot1cum#X^QvUWhd*@0K4tWf4pW8^4%O&-fd(gB88kEtqbsQ!'
    'UyLRbR94a!+qGMU%GCY_M%32>4l=+i5G`wPUzSAP&TFcu2eVt&bD#S~^BtiL*K)jOm94${{nnG`*5A71J(q2F+Xc#y2b|><FEG7*'
    'z|tL8x~9Bk;XZnm8wtbOMxLdEw0L3ZXF^F^;eB=~xtwbFxTun#iP0@UaLAizs2by=%3B1c_e~G7jaR#9zD3_l-h$xz*c9^X-zvaa'
    'Of9jEuOjH~Y`4S?ewi<}Ju|7^t5vn(Ee6?8i6xvj+w^zTwiO;KWtB=prY4Y<v?SKt?SyY`%-SF?1VAL|KccR9`@_yln;h1Tv~ans'
    'S8Y3#!nbBo`Cv8qa+_h}ba7*=61khbL+`%{QUJ1!8C=C|eTlc4c+r3~mY4sA9fvXA(Y)bdXruqLd#4<tVJ7HLx`Xc<W5@id)bar7'
    '0YwdOJ^tqRLd}SakE^QVEcAP<U+KB}u@8El^lvR*6suR)MxetN>iq=f%473J?tX^r#KVd8Y;qe&jG~KguK4N}^W+8Gyz|At9JWd+'
    '1m^~2gak}+CR9-!UQU*#MMq$S0%)lCR-d9$purxejHAYmAU}pTRFqtgq~8HUd88$f@;OskBgAL$(F=Q#ets<+j7DwKChEoTyYE!d'
    'HTUa!+A~HdswRJ+G;=x4pskvtUNqRQdu>$YZN67X+`&*SR7LMD@tqc^B9*7RZ3Mp~js0k;3fFLdC|jcqIZ!Csn_0lL>|jwx8ieWz'
    '>loP3NEHwMhiFbOh_Yl3&R@NQi{ILjwZ~ZuY98EjNdU6H=#E@H^EA)n!PJ+crgC;4l|fwKxfcUVHmK;j&r`-=PR<bz&06P(2V8hK'
    'A*!4jVAOEu%w->oW-sOqGgi0;PzmRM^vZeF1zo$V(^c8&l^PEQQup;v{wNylwna>c+p@)DGZ?m7Q@MQQ$mO(oWHP=a(X@q?#OI3v'
    '=v1`M>Zm1H9b-wULY?1$AR6A7l@RC&hg7<vU!gU0Hejz^D^g&s3TA!j0-WDP@-qb{Z9jz0f~vqBtJgdf#2bjXRZ5YHCR$R@AQGsb'
    '7Yh{3<pF8Y0i%q>Nb|9!CAYQtRlVj*oE+@#e>mW)*Cf5eQ>Mou28$k5svuB~nXf9jf*-o4*I>MA%lp<?Cz}#43x%=D<tH6HUy3fQ'
    'o*%2g&uO$s;Nq{*)0y8h_Kkm_+yYZwvJO@5kL$gO!+Uku(lv*M1rVkLd@aL%+-_>SQ2EAz8fbJ?gvKRlba+#0+MgPLY}rlx?p^5n'
    ';GF+pB@TQ+--L4@+=l_Z&X;WuZjYO;xUI?pZHx->|MObZU24-+h4b7XBfr?nrhW8P+q3rb?1$-eiupF<q$-E`S(>>z!og=%{VEyh'
    'dyy<{Opc!5s21tW)+};WY2x_54*L5i$A|k(We^ZExLn2asRa`SAfm|zS13KVjS*EMT3nZ2mc~5FqWL6)!;#~=3=7Lbb0;~uRlkml'
    's-ofmmIya?HyXDW-r4huE#2;7>#}@|eFC7ImoBae)9GXBP<c+#3NmRpGi{3h=wSi3i>+OJ8s!-4>SED;iI7bcA&}1Klr%@Mj}dzg'
    'Txtj?9?8#C-&dceN;t7STR?#``SYDi$EveP*yve}6HunlfQKB-i|6%GD11Nv#DM8tqXj2B+mQhYm9L~okQBrT5E#aOSoW}0W*IfT'
    'Hv!;mNke<6XuRP!ZSwmzuq2(P1si<T?SP;6YI1L!d9@gfB^q#*bk@i@ok_e>k9>5L-xbDz3j$bAWql?N@dPQLIhw1?TUhu6ku4BO'
    'tn9=aNR4}p7NBox2gH3&wqXBPt?B|bTykAfi!Kx!nFE$wlmXXFm66L^b=i@w(ER$=<XSe$x%p~!i3ZlqD-4`*r)JzGH^c3DeCe?9'
    '%DS|Rp%sEf2Go_XRI3%RO8&6|oXu!zAU@V%1_(s!-X6ND@m5YR=ZF_+|8^Snv4CVBeR^xg0a>2U%Hh_LTv6cU>a%V2SMDmpPnoH@'
    '>V!KJJgtsH-Yq(Zu7R9#eKposp7OvnIc3<ItTqePA8NG;7BElKi)S#Kyl2hdBHPN#UeJ-@wbf+lwN)nn-os-{<!fJORKbMml^TzL'
    '{{mAN2u8Ph!&zi|UJ)vnz%BeY+ZctT7f_?>>c@Pg7&YDvD@9(J%WP^v7pNV=Uiy^DON#*k4ndw-;a0%p78&`YB6hu-=pD;V6J^p='
    'up^La7Pje$T<SDdiv^UbGiw+r3`v~TcGR#TFd!8V^b6+fb((c~bl&DuVxzP4E1qM`eK@!O-Xe*4))GIr#IG%}*SriQ6}QEkt|g*E'
    '4bHj(Q>)S}nwppBHq@(SQ!EaT#+`ssqD=#L`M3x`9)_VIhVJ4~F$uNb>xvTYa1tenoPy4)Ut{!|&hg2+H%%WMbfD_dK?dd5uM9%='
    'zY!`pTgBEef@s<As+Iwn%PsT)wU<Pi8vPHxUWONNigeiJWj2+)jl{lGfrn(<U{BQA>%%ysAr%6CNgH4}E!XGy`!R7ZEclBd_{!d1'
    '&+M(!=<t2KgZl&Rk|qw&Igb#Fn_`t`%m2hhgE2cNujl*ERAp&8?DjEK6V6?BQKWMf4R3TR_a397$M_Lw5v7o5l?qJD(LXM|m8m<1'
    '4aJG%hCBALHBmY!YPPV?+Yh?q<2I?8TS4ef71>g5=)NjSz1a#`dAtcYBkE%tQGee2j(CUfAf;H3;9$*1(7}RFLUshtiGyXqOKm$E'
    'W@(<=Y@Ixnln(_+%Bh5iU3!pI`1VT|Y!5%;m&5&oWAV%G`@?+>nWdlYc1B{+d1KWc4w{T+#%UiLhpX+ZcL|0%(q&KAqzGJijf(8t'
    'pu@D|0IX42YIgP)eLsPHHDIibbpbBj9>x*+2yu-vi^uo&R$1Gjw++vlxgg~(q<Bnwg_{+yNzyjrwLHAqbF-Ao_1^z!UG!H&q?Elp'
    'h|zVh%9%1HVjc$hqdGJG_}kQZ+ZnyCB(D3TxqZ+~dNovG!L9D(FT90D2O?`E$DE?jUBzdd88|^vPo>4k9^U3M&QMhZ1*lZ7O|OfT'
    'Dbc{GkFZ=nU5iPl;n&L0?O5!zU;X%_@B8G1J5%7`P$UyePy6yEQ&2lqcvnyr4gzCufCDzXpt}8|rPp?S#d3{RC(s=i{o_|#ZD|y;'
    'X42w!T)SiQ%Uaf7wNZgeOVCV30kTs@sp?uoBD0Rq%xf{hCYqO*h>fW#BDR#tyGF$g@s|t#b>I*6gKC!I4fz<PCB2Rf5UW&r3$Jjz'
    'UW*2(^y*T*4k_`#ZN}j1jq#x;vAtIk*Xt!KY_D3P))7w6cFztr&=L3!@B|%!I<C?YjOlBcj^L=g4sG+~a10K}&=a!-z6YwIBp4dG'
    'bS*QoaHFQL>sLytq`IY@M}zd%ce1OUca~aXM5!TwQ?r8Y2LtB!)Lsk<zlQdrS9@-j@}=5K2;yq(WhquS(O#(Ywln%>+6$xC*Iojv'
    '`exdTy0)&Ny{w|emD&q+dXn~{Y#*NfqKfRLi(HW@hwm(BztqyvUrNKumoMAaU=&=BD_i3~Nr!nI(qZ=3S+mw&YNgG_D|NJ&eP3_k'
    'QU5G@i#3}y^cEv{*3(;RFt?fBqL|4Fy~SO}dP4pE?$NtXyYDuU>&Arj1kvuedzVP}S~vRI0^V_P|DiJ8UvsVVqK<^#+e_Jgu;G1k'
    'd2f9G7#)%0!LVQS!NgV#HQ8ML+ddq}ee;D{Kt0^my1*KE-$WzO{kQ#@Y^E2KwsX&7UeOh5*IvtE(*>p?l<p=nr*jDm&x;-=^?(wg'
    '2UZz!Uq<6RnUDfujP`5E6NjJi%Fy5KwnKi!F#-4t&sSv&s!Lf%Sowl#DLI!jXs(h>wQ)jWtgnOl&BRnm;Wd)VENJPD1$WIsZVWeE'
    'pH8Q_iPC9QksokW)zB>AdKtC)cq{2=6`k@nZnEAzRp!&H8KCnm<mZUq9`3|m;c^f$*bwveF&GX5DmEdrmrq(baYK7f_{iV-&5@u_'
    ')Wls|Tp$@Pclj;bV+;(Sbf>59G7lTxX8^xqm4E8`Oga~l1Lk#fL6K7F2M`k`T!Xai+Gx0sZuTpFUUq~IxO0+9DHaDg1}Ikx7&52W'
    'aLc&xs(hg|F>YvXN5r6eRRzJ6eO_Z9ie_c_Iw=-2rf3dj(;p~rHk>w#pC5JVERD2C5|dEvWzXVgmA^O?3s|}ly^eaTkLeFU4F<E$'
    'u%KBk8mba7#;+!zqm7(H6pkZ0^Qu>2ViVR$z_?)gb7=-6B3!)es;Il#h)HWFs|n8daiYLVGSD^SL(!hr-_Dy9I8}PY^`&&6Vr9;+'
    'x;m?x>BpXOG0D=!H3zc<a;oW2QmB&`1&K-m#zw|T&3gP$P&>NKthEyM1`sM)sW`e0v2$8?_!*@st_~3i#)qgXm$bTvi!G`|vDLN9'
    'jdTt^9-bcWAM{Vp4nB5NZoVpF$OUAbIX!v<_<N)m;zpP2YMXhp8Q8zqU2~QVIH9&&1@fs7Kjto`yiEy7MYda%;sv}n{E0S~b#{w8'
    'c+YFIJ}V3Rp&Q~n$lvCfq|iabVRTQ9>E(JIx&vkj$VTNY^qg#)QE|;O(bRfFT;ut3Z|c^f4VN3~a$!9SBo^+aU+Ehvp0vzr3L&iW'
    '$FAX@w&*Aa5cxbBN|Po!pWNpdm;(nZF07?H=8oKZPoQ~`>KFM9+#$|y@NNZ%D93lUH_qt?a#YYj)COc}^f}IZJ9G*Iwl_;&SeW#Z'
    'E7VJoEBZiiBRa$RqS5S-;f>z86^Lc@R#HOrHfRqs1E?yt+8WHjQkGR^Pp!t23?nSuQ!d8OYLWL{Rq_KG;sGi7kSez#?^WzR^UvxM'
    'E4eJycTGF9Xb~}#>eUyO)2j>BR15w#QJM-krI~!QFikZGowsn9rfyLip;<-aw~I;C2oD5jE*Rl@wsKw@lBn90*Kt)3;x|h1ou^o&'
    'f^sHq<un~qKvhdzXED`0WB<eo1y7?S91Ez%Cj{kXjz_uQzh4}nYyT)`u#qWO@%<HsTwS#Fsb*Yja%{v6+MV3FXjTB%x81V)_Cwjq'
    'HJj==`nONj9(D|0_(5OJOBi3@?^cetmeXzZ+G^cy<w)Pg=cc4c*hp9ozKO4G!`0S%+x+3bxvR|@aHXH^39Afy+N?o0b+dWgHt1pt'
    'ST|RB+x!`=;c6?H$9lfDTI_9R#^j#0M$EuM>aqLPOD_A<{e~r{bxFru7V2&7R1pmC_H^T-GF2=ZSLR3Q*@R^ydFAHnQlLt)a#8D*'
    'wv2j!Xw6W?-3eAvzIEPxC3{VR6l;=BEjhm^YQy>F7M8QirCNpPI7pic=svlKs#}QeP7Q>4wyH7<WiyOq9$%w0rxLNU$kO&WF0sHP'
    's690)qRN`Y;FnE8m_nu<aacHI@Z3s7aN3GHsjB*nr;&nf8(&oMH?&@1<u@~|vuM$vNs?krbtO5PuQQBhGK;8s$hOMeVt+Z+>cC3U'
    'O0(NmMK0<6C{%J(jcd4?9@{In_WU^)?TV7(`Eydcuy!*l=L@RvpK_&PYpyM~xC7N59W3JM2%GaeY^}yT3c|$dn9~tg-L__OWhyz)'
    '3e>dk>8%8|=`0$;U4+IkXH@S|m|iIDJ&|%GwFs|JB(r^=D)De-k+~fhRQ&~5ue<#@`XHzhud3=-&OjZPwy;wyNISIlb{kn#FfM!>'
    'pI$D3VNpR|1)~GBwp9ZI$##e#m?Fw=ws8ly@vYSCf$2;Zvj}eBX@muJl)$JAVR?KRiW#GnRJp#HloLTXN(kxM+l(bx>5!Seenp~1'
    'J1z0N6)HctvhJWJlZbOPBZrA;oplx8*AqI^49Dw_go*?Cw$4=*_?}XGuTmgSzw2@7D+vQArFRIrBE<5fS-m!M(uVzRPpz)-JLIl9'
    'EF87JAmdi-s%i?c_Rtbtx&|alip_<DRk7n!LQ=wJ=+(DA+)ZN49#rmBB^D47d5c+<eniv3<GMjst7w#y<k|bS*|vDA;nvEu?s~be'
    's{pIuFp5A6!VMT~e3%|*WS1hwo*;KLfhb;0i=aIQ<pjQ`2Q={w_-g}Y)czjsc)rRQ<B;}SpO{Kl+Y-wCy$mvS#qUD*hF}oi>g+u>'
    'uW;0wl`yDElryC$8tsON&^7%yId@OZ-=lZz@L4IRU{o;xT(c)Oj5(6WNY#!RtARUKK15AQsMRl!a%!hmlr5Kr+J)T*p#-!N;P<q%'
    '?`db>)6TwC+S%`&arQmg>~~H!W0A($9jirJMg4Ilnv;k11=(g_U83>4t;~TZNi;hN;fo|%C@JapkZ9jik-n!QJ$0r3`l(32cNWs0'
    'E&+*oeV}#@oHeu?U^yQ&K<jsC^BvJxARM!1)8+hrcFq?iBYoUG+xxjI-plI<Unk>OQ>*jJ{qE{&OZMNDmtiXnhp*5sw0P_;t%tQ='
    'vE9X%dPDW{0r=I`_AR<fSYGkY)gb)^zaWHFPuT`ZUBTnDB<1RNPO>_*r9NvTEh|(XW7o~QWI38V4;W4SoCyp)T=6z2TSEH@RW(d4'
    'nEk`E`wHnl4T7W+E50}n$O1;*6-TJolxq%`W?GSpwOnSE%Uf^mSkZcbC6DLDeO1dcJK^Oe)#o^@M*Q+Dho@#ZxC1QFmi`5D9L}`A'
    '$~vh5!!t5XFZZD~ywAA6@};)ydefuD)+n-hZKq{R&(Q?oa5!K&qY^T`t;KpN3(vC-e#q8d!s6F3s=lS&dx^n2XlHCKy{Rz-O|Xsu'
    'nt5i~^q60Yv*Co4(@jNqsL{W@nb`sO?UFrkd;3qx_$W_E9VG(+two+C)I{E?qSAi&_7~O^RDjFEdfpIv7&~yW&Ru6<EY<t)1L~HU'
    'H>p}y(dBAuM(Y=8i`Ky3O1;w`$0o6<l2<NQD|?}*OJ49&nZb>`ueMwQAZV7+FN3pL5IdoqsDXg<sxlvZ5rioV*?G`LnrcrDBwf>V'
    '!ZR;Vo`1r=1_|<nR%wzLCAtK&l#j=i-)sDV$eVHge!e<h$zRrjKCtV$4kR28X|mDD$cHL`dg&m=j8(4WVaOH!aE|E5#3!6qgR)aO'
    'y+fyc0|Ek}>q{w)4W@Vy+2*67zA<JfnsUu<dc8Ym4rnRGCJKB9z=l%?@LoQLm!!#oN+{#$WpC4a6V2oEWgR?C(Q`eAJz8p<nu$@-'
    's<lcL+3E>sHN#dh$``HHO2lXD2gl$?NA8Vv?5IADCdh^mX0d<%`H|QAtujYcL~We~_)8)r6zH!O9HHQSt+)t3jpQjI5do!a<Jbj;'
    '{D<Y5teH6S*4j~9b*w)pmh$)K3{dz6sU}~NW%307j8PR_rsHkBuMueWV@08_<+-WLU8(chY?8b3Egd!Ab639SuKc&mUHJpjR{jMt'
    'R#<|(lSPQRs~5qQuZyyD(s}hg=PUC*X3>0(ea$fZI#yPb;;i;HwKaJkzRDYra9fZ6ALxpzfB'
)))


def populate_repository(root):
    repo = root / 'reviewed checkout'
    for name, text in REFERENCE.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (repo / '.git').mkdir()
    (repo / '.git/HEAD').write_text(COMMIT + '\n')
    python = repo / '.venv/bin/python'
    python.parent.mkdir(parents=True)
    python.write_text('NOT AN EXECUTABLE ENGINE; process recorder only')
    python.chmod(0o755)
    return repo


class ServingTests(unittest.TestCase):
    def setUp(self):
        import builtins
        original = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name.split('.')[0] in ('torch', 'transformers', 'gr00t', 'zmq'):
                raise AssertionError('Native engine imports forbidden in bounded tests')
            return original(name, *args, **kwargs)
        self.addCleanup(mock.patch.stopall)
        mock.patch('builtins.__import__', side_effect=guarded_import).start()
        mock.patch('socket.socket', side_effect=AssertionError('Network forbidden')).start()

    def test_only_explicit_verified_source_pin_is_supported(self):
        api = consumer()
        self.assertTrue(api.source_supported(configuration()['source']))
        exact_ref = configuration()['source']
        exact_ref.update(ref=COMMIT, revision=None)
        self.assertTrue(api.source_supported(exact_ref))
        for changes in ({'revision': None, 'ref': 'dev'},
                        {'revision': None, 'ref': 'main'},
                        {'revision': 'a' * 40},
                        {'repository': 'https://github.com/example/Isaac-GR00T.git'},
                        {'mode': 'archive'}, {'command': 'anything'}):
            with self.subTest(changes=changes):
                source = {**configuration()['source'], **changes}
                self.assertFalse(api.source_supported(source))

    def test_startup_requires_enabled_review_and_independent_activation(self):
        api = consumer()
        for changes, flags in (({}, {}), ({}, {'activate': True}),
                               ({}, {'reviewed_source': True}),
                               ({'enabled': False}, {'activate': True, 'reviewed_source': True})):
            with self.subTest(changes=changes, flags=flags):
                cfg = configuration()
                cfg['serving'].update(changes)
                hf, process = mock.Mock(), mock.Mock()
                with self.assertRaisesRegex(ValueError, 'activation|review|enabled'):
                    api.execute(cfg, '/tmp/unused', snapshot_download=hf, process_run=process, **flags)
                hf.assert_not_called()
                process.assert_not_called()

    def test_source_contract_requires_actual_head_and_inspected_file_hashes(self):
        api = consumer()
        with tempfile.TemporaryDirectory() as tmp:
            repo = populate_repository(Path(tmp))
            cfg = configuration()
            hf, process = mock.Mock(), mock.Mock()
            for mode in ('dev', 'wrong-head', 'edited-cli', 'missing-policy'):
                with self.subTest(mode=mode):
                    cfg['source']['revision'] = None if mode == 'dev' else COMMIT
                    (repo / '.git/HEAD').write_text('b' * 40 if mode == 'wrong-head' else COMMIT)
                    for name, text in REFERENCE.items():
                        (repo / name).write_text(text)
                    if mode == 'edited-cli':
                        (repo / 'gr00t/eval/run_gr00t_server.py').write_text('# changed')
                    if mode == 'missing-policy':
                        (repo / 'gr00t/policy/gr00t_policy.py').unlink()
                    with self.assertRaisesRegex(ValueError, 'unsupported|HEAD|interface'):
                        api.execute(cfg, str(repo), activate=True, reviewed_source=True,
                                    snapshot_download=hf, process_run=process)
                    hf.assert_not_called()
                    process.assert_not_called()

    def test_invalid_values_and_code_hooks_are_rejected_before_hf_or_process(self):
        api = consumer()
        cases = [('serving.bind', '0.0.0.0'), ('serving.port', True), ('serving.port', 0),
                 ('serving.embodiment', 'NEW; touch /tmp/bad'),
                 ('serving.model.repository', '/some/local/path'),
                 ('serving.model.ref', '--bad'), ('cache_dir', '~/ambient'),
                 ('cache_dir', '/tmp/cache/../escape'), ('command', 'shell'),
                 ('serving.argv', ['--help']), ('serving.model.token', 'ambient')]
        with tempfile.TemporaryDirectory() as tmp:
            repo = populate_repository(Path(tmp))
            for path, value in cases:
                cfg = configuration()
                target = cfg
                keys = path.split('.')
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                hf, process = mock.Mock(), mock.Mock()
                with self.subTest(path=path, value=value), self.assertRaises(ValueError):
                    api.execute(cfg, str(repo), activate=True, reviewed_source=True,
                                snapshot_download=hf, process_run=process)
                hf.assert_not_called()
                process.assert_not_called()

    def test_download_is_a_separate_opt_in_never_activates_and_pins_revision(self):
        api = consumer()
        import inspect
        self.assertIn('allow_download', inspect.signature(api.execute).parameters)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = populate_repository(root)
            cfg = configuration()
            cfg['cache_dir'] = str(root / 'cache')
            cfg['serving']['model']['revision'] = 'c' * 40
            snapshot = root / 'cache/snapshots' / ('c' * 40)
            snapshot.mkdir(parents=True)
            hf, process = mock.Mock(return_value=str(snapshot)), mock.Mock()
            with self.assertRaisesRegex(ValueError, 'download'):
                api.execute(cfg, str(repo), action='download', reviewed_source=True,
                            snapshot_download=hf, process_run=process)
            hf.assert_not_called()
            self.assertEqual(api.execute(cfg, str(repo), action='download', allow_download=True,
                reviewed_source=True, snapshot_download=hf, process_run=process), 0)
            self.assertEqual(hf.call_args.kwargs['revision'], 'c' * 40)
            self.assertFalse(hf.call_args.kwargs['local_files_only'])
            self.assertIs(hf.call_args.kwargs['token'], False)
            process.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'separate'):
                api.execute(cfg, str(repo), activate=True, allow_download=True,
                            reviewed_source=True, snapshot_download=hf, process_run=process)

    def test_hf_consumer_and_engine_do_not_inherit_ambient_auth_or_home(self):
        import os
        import sys
        import types
        api = consumer()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = populate_repository(root)
            cfg = configuration()
            cfg['cache_dir'] = str(root / 'cache')
            snapshot = root / 'cache/snapshots/model'
            snapshot.mkdir(parents=True)
            def fake_snapshot(**kwargs):
                self.assertFalse('HF_TOKEN' in os.environ)
                self.assertFalse('HUGGING_FACE_HUB_TOKEN' in os.environ)
                self.assertEqual(os.environ['HOME'], str(root / 'cache/.runtime-home'))
                self.assertEqual(os.environ['HF_HUB_OFFLINE'], '1')
                return str(snapshot)
            hf = types.ModuleType('huggingface_hub')
            setattr(hf, 'snapshot_download', fake_snapshot)
            with mock.patch.dict(sys.modules, {'huggingface_hub': hf}), mock.patch.dict(os.environ,
                    {'HF_TOKEN': 'denied-test-token', 'HUGGING_FACE_HUB_TOKEN': 'denied',
                     'HOME': '/never-read-this-home', 'HF_ENDPOINT': 'https://invalid.example'}):
                api.execute(cfg, str(repo), activate=True, reviewed_source=True,
                            process_run=mock.Mock(return_value=mock.Mock(returncode=0)))
                self.assertEqual(os.environ['HF_TOKEN'], 'denied-test-token')

    def test_snapshot_failures_and_out_of_cache_paths_never_start_engine(self):
        api = consumer()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = populate_repository(root)
            cfg = configuration()
            cfg['cache_dir'] = str(root / 'cache')
            outside = root / 'outside'
            outside.mkdir()
            for snapshot in (str(outside), str(root / 'cache/missing'), 'relative/model'):
                process = mock.Mock()
                with self.subTest(snapshot=snapshot), self.assertRaisesRegex(ValueError, 'snapshot'):
                    api.execute(cfg, str(repo), activate=True, reviewed_source=True,
                                snapshot_download=mock.Mock(return_value=snapshot), process_run=process)
                process.assert_not_called()
            process = mock.Mock()
            with self.assertRaisesRegex(ValueError, 'snapshot'):
                api.execute(cfg, str(repo), activate=True, reviewed_source=True,
                    snapshot_download=mock.Mock(side_effect=RuntimeError('cache miss or gated repo')),
                    process_run=process)
            process.assert_not_called()

    def test_cli_consumes_file_and_inline_json_with_explicit_gates(self):
        api = consumer()
        self.assertTrue(hasattr(api, 'main'), 'bounded wrapper CLI missing')
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = populate_repository(root)
            cfg = configuration()
            cfg['cache_dir'] = str(root / 'cache')
            snapshot = root / 'cache/snapshots/model'
            snapshot.mkdir(parents=True)
            path = root / 'serving.json'
            path.write_text(json.dumps(cfg))
            for config_args in (['--config', str(path)], ['--config-json', json.dumps(cfg)]):
                with mock.patch.object(api, 'execute', wraps=api.execute) as execute, \
                        mock.patch.dict('sys.modules', {'huggingface_hub': mock.Mock(
                            snapshot_download=mock.Mock(return_value=str(snapshot)))}), \
                        mock.patch.object(api.subprocess, 'run', return_value=mock.Mock(returncode=0)) as run:
                    args = ['serve', '--repo-dir', str(repo), *config_args]
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(api.main(args), 2)
                    run.assert_not_called()
                    self.assertEqual(api.main(args + ['--activate', '--reviewed-source']), 0)
                    run.assert_called_once()
                    self.assertEqual(execute.call_args.args[0], cfg)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(api.main(['serve', '--repo-dir', str(repo),
                    '--config-json', '{"source": {}, "source": {}}', '--activate', '--reviewed-source']), 2)

    def test_adapters_map_only_the_reviewed_pin_and_leave_default_dev_blocked(self):
        from src.python.profile_adapters import render_profile
        from src.python.workstation_profile import resolve_profile
        selected = resolve_profile('full')['profile']
        before = deepcopy(selected)
        for name in ('local', 'ansible'):
            default = render_profile(selected, name, '/home/reviewer')
            fields = {k: v for k, v in default['coverage'].items() if k.startswith('serving.')}
            self.assertTrue(all(v['status'] == 'unsupported' and v['required'] for v in fields.values()))
            pinned = deepcopy(selected)
            pinned['components']['gr00t']['source']['revision'] = COMMIT
            report = render_profile(pinned, name, '/home/reviewer')
            key = 'gr00t_serving' if name == 'local' else 'profile_gr00t_serving'
            self.assertIn(key, report['artifact'], 'reviewed serving config has no actual consumer binding')
            cfg = report['artifact'][key]
            self.assertEqual(cfg['source'], pinned['components']['gr00t']['source'])
            self.assertEqual(cfg['serving'], pinned['serving'])
            self.assertEqual(cfg['cache_dir'], '/home/reviewer/.cache/isaac-gr00t/hub')
            self.assertEqual(report['coverage']['serving.bind']['status'], 'mapped')
            self.assertEqual(report['coverage']['serving.model.revision']['status'], 'unspecified')
            self.assertFalse(report['apply_supported'])
            self.assertFalse(report['runtime_verified'])
            if name == 'ansible':
                self.assertFalse(report['artifact']['gr00t_service_enabled'])
                self.assertNotIn('profile_gr00t_serving_activate', report['artifact'])
        self.assertEqual(selected, before)

    def test_local_profile_branch_uses_fixed_argv_without_legacy_probes(self):
        import subprocess
        import shlex
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'reviewed checkout'
            script = '\n'.join([
                'set -eu', 'source ' + shlex.quote(str(ROOT / 'isaac-installer/lib/modules/gr00t.sh')),
                'resolve_active_repo_dir() { printf "%s" ' + shlex.quote(str(repo)) + '; }',
                'run_as_user() { exit 91; }', 'is_port_in_use() { exit 92; }',
                'run_profile_argv() { /usr/bin/python3 -c \'import json,sys; print(json.dumps(sys.argv[1:]))\' "$@"; }',
                'cmd_gr00t profile-serving serve --config /tmp/reviewed.json --activate --reviewed-source'])
            result = subprocess.run(['/bin/bash', '-c', script], capture_output=True, text=True,
                                    env={'HOME': tmp, 'PATH': '/usr/bin:/bin'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.strip().startswith('['), 'profile branch did not invoke bounded wrapper')
            args = json.loads(result.stdout)
            self.assertIn(str(repo / '.venv/bin/python'), args)
            self.assertIn(str(ROOT / 'src/python/gr00t_serving.py'), args)
            self.assertIn('--activate', args)
            self.assertEqual(args[-2:], ['--repo-dir', str(repo)])
            self.assertNotIn('uv', args)
            self.assertNotIn('python3', args)

    def test_ansible_launcher_embeds_same_wrapper_and_service_does_not_activate_by_default(self):
        import shlex
        import subprocess
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
        templates = ROOT / 'src/ansible/roles/gr00t/templates'
        env = Environment(loader=FileSystemLoader(str(templates)), undefined=StrictUndefined)
        env.filters.update(bool=bool, quote=shlex.quote, to_json=json.dumps)
        def lookup(kind, path):
            self.assertEqual(kind, 'file')
            self.assertEqual(Path(path).resolve(), ROOT / 'src/python/gr00t_serving.py')
            return Path(path).read_text()
        env.globals['lookup'] = lookup
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / 'reviewed checkout'
            python = repo / '.venv/bin/python'
            python.parent.mkdir(parents=True)
            # A process recorder, not a Python/GR00T engine.
            python.write_text('#!/bin/bash\n/usr/bin/python3 -c \'import sys,json; print(json.dumps(sys.argv[1:])); print(sys.stdin.read())\' "$@"\n')
            python.chmod(0o755)
            variables = dict(profile_gr00t_isolated=True, profile_gr00t_serving=configuration(),
                             gr00t_dir=str(repo), playbook_dir=str(ROOT / 'src/ansible'),
                             gr00t_port=5561, ansible_user='fixture')
            script = env.get_template('gr00t-policy-server.sh.j2').render(**variables)
            self.assertIn('--config-json', script, 'Ansible launcher still has no bounded consumer')
            path = root / 'launcher.sh'
            path.write_text(script)
            result = subprocess.run(['/bin/bash', str(path), 'serve', '--activate', '--reviewed-source'],
                                    capture_output=True, text=True, env={'HOME': tmp, 'PATH': '/usr/bin:/bin'})
            self.assertEqual(result.returncode, 0, result.stderr)
            args_text, embedded = result.stdout.split('\n', 1)
            args = json.loads(args_text)
            self.assertEqual(args[:3], ['-I', '-', 'serve'])
            self.assertEqual(json.loads(args[args.index('--config-json') + 1]), configuration())
            self.assertEqual(embedded.strip(), (ROOT / 'src/python/gr00t_serving.py').read_text().strip())
            unit = env.get_template('isaac-gr00t.service.j2').render(**variables)
            self.assertNotIn('--activate', unit)
            self.assertNotIn('--reviewed-source', unit)
            self.assertIn('Restart=no', unit)
            active = env.get_template('isaac-gr00t.service.j2').render(**variables,
                profile_gr00t_serving_activate=True, profile_gr00t_serving_reviewed=True)
            self.assertIn('--activate', active)
            self.assertIn('--reviewed-source', active)
            self.assertNotIn('systemctl', script)
            self.assertNotIn('systemctl', unit)

    def test_ast_extracted_reference_cli_and_policy_types_match_consumer_argv(self):
        from dataclasses import dataclass, fields
        api = consumer()
        self.assertEqual(api.INTERFACE_HASHES, {
            path: hashlib.sha256(text.encode()).hexdigest() for path, text in REFERENCE.items()})
        tree = ast.parse(REFERENCE['gr00t/eval/run_gr00t_server.py'])
        config = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ServerConfig')
        # Execute the actual dataclass declaration ONLY; its type/default contract
        # needs no engine imports. The upstream main/CLI/server are never executed.
        namespace = {'dataclass': dataclass, 'DEFAULT_MODEL_SERVER_PORT': 5555}
        exec(compile(ast.Module(body=[config], type_ignores=[]), '<upstream-ServerConfig-only>', 'exec'), namespace)
        cls = namespace['ServerConfig']
        native = cls(host='127.0.0.1', port=5561, embodiment_tag='NEW_EMBODIMENT', model_path='/tmp/model')
        names = {f.name for f in fields(cls)}
        for flag in ('--host', '--port', '--embodiment-tag', '--model-path'):
            self.assertIn(flag[2:].replace('-', '_'), names)
        self.assertIs(type(native.port), int)
        self.assertIs(type(native.host), str)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        self.assertTrue(any(ast.unparse(n.func) == 'tyro.cli' and ast.unparse(n.args[0]) == 'ServerConfig'
                            for n in calls if n.args))
        server = next(n for n in calls if ast.unparse(n.func) == 'PolicyServer')
        self.assertEqual({k.arg: ast.unparse(k.value) for k in server.keywords},
                         {'policy': 'policy', 'host': 'config.host', 'port': 'config.port'})
        policy_call = next(n for n in calls if ast.unparse(n.func) == 'Gr00tPolicy')
        self.assertEqual(next(ast.unparse(k.value) for k in policy_call.keywords if k.arg == 'model_path'), 'config.model_path')
        policy_tree = ast.parse(REFERENCE['gr00t/policy/gr00t_policy.py'])
        policy_cls = next(n for n in policy_tree.body if isinstance(n, ast.ClassDef) and n.name == 'Gr00tPolicy')
        ctor = next(n for n in policy_cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
        self.assertEqual([n.arg for n in ctor.args.args], ['self', 'embodiment_tag', 'model_path'])
        self.assertEqual([n.arg for n in ctor.args.kwonlyargs], ['device', 'strict'])
        self.assertIsNone(ctor.args.kwarg)
        server_tree = ast.parse(REFERENCE['gr00t/policy/server_client.py'])
        bind = next(n for n in ast.walk(server_tree) if isinstance(n, ast.Call)
                    and ast.unparse(n.func) == 'self.socket.bind')
        self.assertEqual(ast.unparse(bind.args[0]), "f'tcp://{host}:{port}'")

    def test_malformed_source_selectors_do_not_reuse_a_ref_pin(self):
        api = consumer()
        for value in ('', False, 0, [], {}):
            source = {'mode': 'git', 'repository': REPOSITORY, 'ref': COMMIT, 'revision': value}
            with self.subTest(value=value):
                self.assertFalse(api.source_supported(source))

    def test_malformed_config_shapes_fail_closed_without_loading_hub(self):
        import contextlib
        import io
        api = consumer()
        for bad in (None, [], 'text', {'enabled': True}):
            cfg = configuration()
            cfg['serving'] = bad
            with self.subTest(bad=bad), contextlib.redirect_stderr(io.StringIO()), \
                    mock.patch.object(api.subprocess, 'run', side_effect=AssertionError('process')):
                self.assertEqual(api.main(['serve', '--repo-dir', '/tmp/not-inspected',
                    '--config-json', json.dumps(cfg), '--activate', '--reviewed-source']), 2)

    def test_real_consumer_passes_cached_snapshot_to_fixed_native_argv(self):
        api = consumer()
        self.assertTrue(hasattr(api, 'execute'), 'explicit serving execution consumer missing')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = populate_repository(root)
            snapshot = root / 'cache/snapshots/model-pin'
            snapshot.mkdir(parents=True)
            cfg = configuration()
            cfg['cache_dir'] = str(root / 'cache')
            hf = mock.Mock(return_value=str(snapshot))
            process = mock.Mock(return_value=mock.Mock(returncode=17))
            result = api.execute(cfg, str(repo), activate=True, reviewed_source=True,
                                 snapshot_download=hf, process_run=process)
            self.assertEqual(result, 17)
            hf.assert_called_once_with(repo_id='nvidia/GR00T-N1.7-3B', revision='main',
                                       cache_dir=str(root / 'cache'), token=False,
                                       local_files_only=True, endpoint='https://huggingface.co')
            args, kwargs = process.call_args
            self.assertEqual(args[0], [str(repo / '.venv/bin/python'), '-I',
                str(repo / 'gr00t/eval/run_gr00t_server.py'), '--host', '127.0.0.1',
                '--port', '5561', '--embodiment-tag', 'NEW_EMBODIMENT',
                '--model-path', str(snapshot)])
            self.assertEqual(kwargs['cwd'], str(repo))
            self.assertEqual(kwargs['env']['HF_HUB_OFFLINE'], '1')
            self.assertEqual(kwargs['env']['TRANSFORMERS_OFFLINE'], '1')
            self.assertNotIn('HF_TOKEN', kwargs['env'])
            self.assertNotIn('PYTHONPATH', kwargs['env'])


if __name__ == '__main__':
    unittest.main()

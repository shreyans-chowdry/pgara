rnd:
    enter 4
    lwg   r0, @seed
    li    t1, 1103515245
    mul   r0, r0, t1
    addi  r0, r0, 12345
    swg   r0, @seed
    lwg   r0, @seed
    li    t1, 65536
    div   r0, r0, t1
    li    t1, 32768
    rem   r0, r0, t1
    li    t1, 0
    blt   r0, t1, rnd.then1
    j     rnd.endif2
rnd.then1:
    neg   r0, r0
rnd.endif2:
    mv    rv, r0
    leave 
    ret   
main:
    enter 16
    input r0
    swg   r0, @seed
    input r0
    li    r1, 0
main.for1:
    li    t1, 1024
    blt   r1, t1, main.body2
    j     main.endfor4
main.body2:
    sw    r0, 12(fp)
    sw    r1, 13(fp)
    call  rnd
    lw    r0, 12(fp)
    lw    r1, 13(fp)
    mv    r2, rv
    li    t1, 1000
    rem   r3, r2, t1
    blt   r3, r0, main.then5
    j     main.else7
main.then5:
    la    r3, @data
    li    t1, 50
    rem   r2, r2, t1
    neg   r2, r2
    addi  r2, r2, -1
    swx   r2, r3, r1
    j     main.endif6
main.else7:
    la    r3, @data
    li    t1, 200
    rem   r2, r2, t1
    swx   r2, r3, r1
main.endif6:
    addi  r1, r1, 1
    j     main.for1
main.endfor4:
    li    t0, 0
    sw    t0, 0(fp)
    li    r0, 0
    li    r1, -1
    li    r2, 0
    li    r3, 0
    li    t0, 0
    sw    t0, 1(fp)
    li    t0, 0
    sw    t0, 2(fp)
    li    t0, 0
    sw    t0, 3(fp)
    li    t0, 0
    sw    t0, 4(fp)
main.for8:
    lw    t0, 0(fp)
    li    t1, 4
    blt   t0, t1, main.body9
    j     main.endfor11
main.body9:
    sw    r0, 5(fp)
    sw    r1, 6(fp)
    li    r1, 0
    sw    r2, 7(fp)
    sw    r3, 8(fp)
    lw    r0, 2(fp)
    lw    r2, 3(fp)
main.for12:
    li    t1, 1024
    blt   r1, t1, main.body13
    j     main.endfor15
main.body13:
    la    r3, @data
    lwx   r3, r3, r1
    li    t1, 0
    blt   r3, t1, main.then16
    j     main.else18
main.then16:
    lw    t0, 8(fp)
    addi  t0, t0, 1
    sw    t0, 8(fp)
    lw    t0, 7(fp)
    add   t0, t0, r3
    sw    t0, 7(fp)
    lw    t0, 6(fp)
    li    t1, 0
    bge   t0, t1, main.then19
    lw    r3, 5(fp)
    j     main.endif20
main.then19:
    lw    t1, 6(fp)
    sub   r3, r1, t1
    lw    t0, 5(fp)
    add   r3, t0, r3
main.endif20:
    sw    r3, 5(fp)
    sw    r1, 6(fp)
    j     main.endif17
main.else18:
    add   t0, r3, r3
    sw    t0, 9(fp)
    lw    t0, 4(fp)
    lw    t1, 9(fp)
    add   t0, t0, t1
    sw    t0, 4(fp)
    li    t1, 7
    rem   t0, r1, t1
    sw    t0, 10(fp)
    mv    t1, t0
    mul   t0, r3, t1
    sw    t0, 11(fp)
    mv    t1, t0
    add   r2, r2, t1
    addi  r0, r0, 1
    lw    t1, 1(fp)
    bgt   r3, t1, main.then21
    j     main.endif17
main.then21:
    sw    r3, 1(fp)
main.endif17:
    addi  r1, r1, 1
    j     main.for12
main.endfor15:
    lw    t0, 0(fp)
    addi  r1, t0, 1
    sw    r1, 0(fp)
    lw    r1, 6(fp)
    lw    r3, 8(fp)
    sw    r0, 2(fp)
    lw    r0, 5(fp)
    sw    r2, 3(fp)
    lw    r2, 7(fp)
    j     main.for8
main.endfor11:
    lw    t0, 4(fp)
    print t0
    lw    t0, 3(fp)
    print t0
    lw    t0, 2(fp)
    print t0
    lw    t0, 1(fp)
    print t0
    print r3
    print r2
    print r1
    print r0
    li    rv, 0
    leave 
    ret   

; String routines for '$'-terminated strings in DS
;
; rt_print_str
;   Inputs:  DS:DX -> '$'-terminated string
;   Preserves: AX (saved/restored); BX,CX,SI,DI,DS,ES,BP,SP not modified
;   Clobbers: FLAGS; DOS call may alter AH internally but we restore AX
;
; rt_str_cmp
;   Inputs:  DS:SI -> s1, DS:DI -> s2 ('$'-terminated)
;   Returns: AX = -1 if s1 < s2, 0 if equal, 1 if s1 > s2 (unsigned byte compare)
;   Preserves: BX (saved/restored)
;   Clobbers: AX, SI, DI, FLAGS
;

global rt_print_str
rt_print_str:
    push ax
    mov ah, 0x09
    int 0x21
    pop ax
    ret

; Print DOS CRLF ("\r\n") newline
global rt_print_newline
rt_print_newline:
    push ax
    push dx
    mov dl, 0x0D      ; '\r'
    mov ah, 0x02
    int 0x21
    mov dl, 0x0A      ; '\n'
    mov ah, 0x02
    int 0x21
    pop dx
    pop ax
    ret

; Compare strings byte by byte until '$' or difference
; Uses AL, BL as current chars

global rt_str_cmp
rt_str_cmp:
    push bx
.next_char:
    mov al, [si]
    mov bl, [di]
    cmp al, bl
    jne .diff
    cmp al, '$'
    je .equal
    inc si
    inc di
    jmp .next_char
.diff:
    ; Determine order with unsigned compare
    jb .less
    ja .greater
.equal:
    xor ax, ax
    jmp .done
.less:
    mov ax, -1
    jmp .done
.greater:
    mov ax, 1
.done:
    pop bx
    ret

; Vortex CLI Enhanced - NASM x64 (NodeMCU + LCD 16x2 Controller)
; Build: nasm -f win64 main.asm -o main.obj
;        gcc -o main.exe main.obj -lkernel32 -mconsole

bits 64
default rel

; Windows API Constants
STD_INPUT_HANDLE  equ -10
STD_OUTPUT_HANDLE equ -11
GENERIC_READ      equ 0x80000000
GENERIC_WRITE     equ 0x40000000
OPEN_EXISTING     equ 3

section .data
    ; === UI Messages ===
    msgBanner:      db 13, 10
                    db "  ===========================================", 13, 10
                    db "   VORTEX LCD CONTROLLER (Assembly Edition)", 13, 10
                    db "   NodeMCU + 16x2 LCD", 13, 10
                    db "  ===========================================", 13, 10, 0
    
    msgMenu:        db 13, 10
                    db "  [COMMANDS]", 13, 10
                    db "  ------------------------------------------", 13, 10
                    db "  1 = Visit Mode      2 = Music Mode", 13, 10
                    db "  3 = Clock Mode      4 = Text Mode", 13, 10
                    db "  5 = System Mode     6 = Screen Mode", 13, 10
                    db "  ------------------------------------------", 13, 10
                    db "  t = Send Text       c = Send Clock", 13, 10
                    db "  l = Send 2-Line     r = Reset Device", 13, 10
                    db "  m = Show Menu       q = Quit", 13, 10
                    db "  ------------------------------------------", 13, 10
                    db "  (Or type raw command: MODE:1, TEXT:Hi...)", 13, 10, 0
    
    msgPrompt:      db "Enter COM Port (e.g. COM3): ", 0
    msgConnected:   db 13, 10, "  [OK] Connected to ", 0
    msgConnected2:  db " @ 115200 baud", 13, 10, 0
    msgCmdPrompt:   db 13, 10, "  > ", 0
    msgError:       db "  [ERROR] Cannot open port. Code: ", 0
    msgNewLine:     db 13, 10, 0
    msgSent:        db "  [SENT] ", 0
    
    ; === Input Prompts ===
    msgAskText:     db "  Enter text (max 32 chars): ", 0
    msgAskLine1:    db "  Line 1 (max 16 chars): ", 0
    msgAskLine2:    db "  Line 2 (max 16 chars): ", 0
    msgAskTime:     db "  Enter time (e.g. 12:30): ", 0
    msgAskDate:     db "  Enter date/info: ", 0
    
    ; === Command Prefixes ===
    cmdMode1:       db "MODE:1", 10, 0
    cmdMode3:       db "MODE:3", 10, 0
    cmdMode4:       db "MODE:4", 10, 0
    cmdMode5:       db "MODE:5", 10, 0
    cmdMode7:       db "MODE:7", 10, 0
    cmdMode8:       db "MODE:8", 10, 0
    cmdReset:       db "RESET", 10, 0
    
    hexChars:       db "0123456789ABCDEF"
    
    ; === Variables in .data instead of .bss ===
    hStdIn:         dq 0
    hStdOut:        dq 0
    hSerial:        dq 0
    bytesRW:        dq 0
    
    inputBuf:       times 256 db 0
    serialBuf:      times 256 db 0
    comPort:        times 64 db 0
    dcb:            times 96 db 0
    timeouts:       times 20 db 0
    tempBuf:        times 64 db 0
    cmdBuf:         times 128 db 0
    line1Buf:       times 32 db 0
    line2Buf:       times 32 db 0

section .text
    global main
    
    extern GetStdHandle
    extern ReadFile
    extern WriteFile
    extern CreateFileA
    extern GetCommState
    extern SetCommState
    extern SetCommTimeouts
    extern CloseHandle
    extern GetLastError
    extern ExitProcess
    extern Sleep

; ============================================================
; strlen: RCX = string ptr, returns RAX = length
; ============================================================
strlen:
    xor rax, rax
.loop:
    cmp byte [rcx + rax], 0
    je .done
    inc rax
    jmp .loop
.done:
    ret

; ============================================================
; print: RCX = null-terminated string
; ============================================================
print:
    push rbp
    mov rbp, rsp
    sub rsp, 48
    push r12
    
    mov r12, rcx
    call strlen
    
    mov rcx, [rel hStdOut]
    mov rdx, r12
    mov r8, rax
    lea r9, [rel bytesRW]
    mov qword [rsp+32], 0
    call WriteFile
    
    pop r12
    leave
    ret

; ============================================================
; print_hex: RAX = value to print (32-bit)
; ============================================================
print_hex:
    push rbp
    mov rbp, rsp
    sub rsp, 48
    push rbx
    push r12
    
    mov rbx, rax
    mov r12, 8
    
.loop:
    dec r12
    mov rcx, r12
    shl rcx, 2
    mov rax, rbx
    shr rax, cl
    and rax, 0xF
    
    lea rdx, [rel hexChars]
    mov al, [rdx + rax]
    lea rdx, [rel tempBuf]
    mov [rdx], al
    mov byte [rdx+1], 0
    
    lea rcx, [rel tempBuf]
    call print
    
    cmp r12, 0
    jg .loop
    
    pop r12
    pop rbx
    leave
    ret

; ============================================================
; read_line: RCX = buffer, RDX = max size
; Returns RAX = length (excluding CRLF)
; ============================================================
read_line:
    push rbp
    mov rbp, rsp
    sub rsp, 48
    push rbx
    push r12
    
    mov r12, rcx
    mov rbx, rdx
    
    mov rcx, [rel hStdIn]
    mov rdx, r12
    mov r8, rbx
    lea r9, [rel bytesRW]
    mov qword [rsp+32], 0
    call ReadFile
    
    mov rax, [rel bytesRW]
    cmp rax, 0
    je .done
    
    mov rcx, rax
.strip:
    cmp rcx, 0
    je .set_len
    dec rcx
    mov dl, [r12 + rcx]
    cmp dl, 10
    je .zero_it
    cmp dl, 13
    je .zero_it
    jmp .set_len
.zero_it:
    mov byte [r12 + rcx], 0
    jmp .strip
.set_len:
    inc rcx
    mov rax, rcx
    
.done:
    pop r12
    pop rbx
    leave
    ret

; ============================================================
; send_serial: RCX = string to send
; ============================================================
send_serial:
    push rbp
    mov rbp, rsp
    sub rsp, 48
    push r12
    push r13
    
    mov r12, rcx
    call strlen
    mov r13, rax            ; length
    
    ; Print what we're sending
    lea rcx, [rel msgSent]
    call print
    mov rcx, r12
    call print
    lea rcx, [rel msgNewLine]
    call print
    
    ; Send to serial
    mov rcx, [rel hSerial]
    mov rdx, r12
    mov r8, r13
    lea r9, [rel bytesRW]
    mov qword [rsp+32], 0
    call WriteFile
    
    pop r13
    pop r12
    leave
    ret

; ============================================================
; send_with_newline: RCX = string (will append \n and send)
; ============================================================
send_with_newline:
    push rbp
    mov rbp, rsp
    sub rsp, 48
    push r12
    push r13
    push r14
    
    mov r12, rcx
    call strlen
    mov r13, rax            ; length
    
    ; Copy to cmdBuf
    lea r14, [rel cmdBuf]
    xor rcx, rcx
.copy:
    cmp rcx, r13
    jge .append_nl
    mov al, [r12 + rcx]
    mov [r14 + rcx], al
    inc rcx
    jmp .copy
    
.append_nl:
    mov byte [r14 + r13], 10     ; \n
    mov byte [r14 + r13 + 1], 0  ; null
    
    lea rcx, [rel cmdBuf]
    call send_serial
    
    pop r14
    pop r13
    pop r12
    leave
    ret

; ============================================================
; ask_and_send_text: Ask for text and send TEXT:<input>
; ============================================================
ask_and_send_text:
    push rbp
    mov rbp, rsp
    sub rsp, 48
    push r12
    
    lea rcx, [rel msgAskText]
    call print
    
    lea rcx, [rel inputBuf]
    mov rdx, 64
    call read_line
    
    cmp rax, 0
    je .done
    
    mov r12, rax            ; save length
    
    ; Build TEXT:<input>
    lea rcx, [rel cmdBuf]
    mov byte [rcx], 'T'
    mov byte [rcx+1], 'E'
    mov byte [rcx+2], 'X'
    mov byte [rcx+3], 'T'
    mov byte [rcx+4], ':'
    
    ; Copy input
    lea rdx, [rel inputBuf]
    xor r8, r8
.copy:
    cmp r8, r12
    jge .finish
    mov al, [rdx + r8]
    cmp al, 0
    je .finish
    mov [rcx + 5 + r8], al
    inc r8
    jmp .copy
    
.finish:
    mov byte [rcx + 5 + r8], 10
    mov byte [rcx + 6 + r8], 0
    
    lea rcx, [rel cmdBuf]
    call send_serial
    
.done:
    pop r12
    leave
    ret

; ============================================================
; ask_and_send_clock: Builds CLOCK:<time>|<info>
; ============================================================
ask_and_send_clock:
    push rbp
    mov rbp, rsp
    sub rsp, 48
    push r12
    push r13
    
    ; Ask time
    lea rcx, [rel msgAskTime]
    call print
    lea rcx, [rel line1Buf]
    mov rdx, 20
    call read_line
    mov r12, rax
    
    ; Ask date
    lea rcx, [rel msgAskDate]
    call print
    lea rcx, [rel line2Buf]
    mov rdx, 20
    call read_line
    mov r13, rax
    
    ; Build CLOCK:<time>|<info>
    lea rcx, [rel cmdBuf]
    mov byte [rcx], 'C'
    mov byte [rcx+1], 'L'
    mov byte [rcx+2], 'O'
    mov byte [rcx+3], 'C'
    mov byte [rcx+4], 'K'
    mov byte [rcx+5], ':'
    
    ; Copy time
    lea rdx, [rel line1Buf]
    xor r8, r8
.copy1:
    cmp r8, r12
    jge .add_pipe
    mov al, [rdx + r8]
    cmp al, 0
    je .add_pipe
    mov [rcx + 6 + r8], al
    inc r8
    jmp .copy1
    
.add_pipe:
    mov byte [rcx + 6 + r8], '|'
    lea r9, [r8 + 7]        ; position after pipe
    
    ; Copy info
    lea rdx, [rel line2Buf]
    xor r8, r8
.copy2:
    cmp r8, r13
    jge .finish
    mov al, [rdx + r8]
    cmp al, 0
    je .finish
    mov [rcx + r9], al
    inc r9
    inc r8
    jmp .copy2
    
.finish:
    mov byte [rcx + r9], 10
    mov byte [rcx + r9 + 1], 0
    
    lea rcx, [rel cmdBuf]
    call send_serial
    
    pop r13
    pop r12
    leave
    ret

; ============================================================
; ask_and_send_2line: Sends 2 lines as TEXT (padded to 16 each)
; ============================================================
ask_and_send_2line:
    push rbp
    mov rbp, rsp
    sub rsp, 48
    push r12
    push r13
    
    ; Ask line1
    lea rcx, [rel msgAskLine1]
    call print
    lea rcx, [rel line1Buf]
    mov rdx, 20
    call read_line
    
    ; Ask line2
    lea rcx, [rel msgAskLine2]
    call print
    lea rcx, [rel line2Buf]
    mov rdx, 20
    call read_line
    
    ; Build TEXT:<line1 padded><line2 padded>
    lea rcx, [rel cmdBuf]
    mov byte [rcx], 'T'
    mov byte [rcx+1], 'E'
    mov byte [rcx+2], 'X'
    mov byte [rcx+3], 'T'
    mov byte [rcx+4], ':'
    
    ; Copy line1 (pad to 16)
    lea rdx, [rel line1Buf]
    xor r8, r8
.copy1:
    cmp r8, 16
    jge .copy2_start
    mov al, [rdx + r8]
    cmp al, 0
    je .pad1
    mov [rcx + 5 + r8], al
    inc r8
    jmp .copy1
.pad1:
    mov byte [rcx + 5 + r8], ' '
    inc r8
    jmp .copy1
    
.copy2_start:
    lea rdx, [rel line2Buf]
    xor r8, r8
.copy2:
    cmp r8, 16
    jge .finish
    mov al, [rdx + r8]
    cmp al, 0
    je .pad2
    mov [rcx + 21 + r8], al
    inc r8
    jmp .copy2
.pad2:
    mov byte [rcx + 21 + r8], ' '
    inc r8
    jmp .copy2
    
.finish:
    mov byte [rcx + 37], 10
    mov byte [rcx + 38], 0
    
    lea rcx, [rel cmdBuf]
    call send_serial
    
    pop r13
    pop r12
    leave
    ret

; ============================================================
; main
; ============================================================
main:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    
    ; Get handles
    mov rcx, STD_OUTPUT_HANDLE
    call GetStdHandle
    mov [rel hStdOut], rax
    
    mov rcx, STD_INPUT_HANDLE
    call GetStdHandle
    mov [rel hStdIn], rax
    
    ; Print banner
    lea rcx, [rel msgBanner]
    call print

.ask_port:
    lea rcx, [rel msgPrompt]
    call print
    
    lea rcx, [rel comPort]
    mov rdx, 60
    call read_line
    
    cmp rax, 3
    jl .ask_port
    
    ; Open serial port
    lea rcx, [rel comPort]
    mov rdx, GENERIC_READ | GENERIC_WRITE
    xor r8, r8
    xor r9, r9
    mov qword [rsp+32], OPEN_EXISTING
    mov qword [rsp+40], 0
    mov qword [rsp+48], 0
    call CreateFileA
    
    mov [rel hSerial], rax
    cmp rax, -1
    je .open_error
    
    ; Configure serial port
    mov rcx, [rel hSerial]
    lea rdx, [rel dcb]
    call GetCommState
    test eax, eax
    jz .open_error
    
    lea rcx, [rel dcb]
    mov dword [rcx+4], 115200
    mov byte [rcx+18], 8
    mov byte [rcx+19], 0
    mov byte [rcx+20], 0
    
    mov rcx, [rel hSerial]
    lea rdx, [rel dcb]
    call SetCommState
    test eax, eax
    jz .open_error
    
    lea rcx, [rel timeouts]
    mov dword [rcx], 0xFFFFFFFF
    mov dword [rcx+4], 0
    mov dword [rcx+8], 0
    mov dword [rcx+12], 0
    mov dword [rcx+16], 0
    
    mov rcx, [rel hSerial]
    lea rdx, [rel timeouts]
    call SetCommTimeouts
    
    ; Print success
    lea rcx, [rel msgConnected]
    call print
    lea rcx, [rel comPort]
    call print
    lea rcx, [rel msgConnected2]
    call print
    
    ; Show menu
    lea rcx, [rel msgMenu]
    call print

; ============================================================
; Command loop
; ============================================================
.cmd_loop:
    lea rcx, [rel msgCmdPrompt]
    call print
    
    lea rcx, [rel inputBuf]
    mov rdx, 250
    call read_line
    mov r12, rax
    
    cmp rax, 0
    je .cmd_loop
    
    ; Check single-char commands
    cmp rax, 1
    jne .check_raw
    
    lea rcx, [rel inputBuf]
    mov al, [rcx]
    
    cmp al, '1'
    jne .c2
    lea rcx, [rel cmdMode1]
    call send_serial
    jmp .cmd_loop
    
.c2:
    cmp al, '2'
    jne .c3
    lea rcx, [rel cmdMode3]
    call send_serial
    jmp .cmd_loop
    
.c3:
    cmp al, '3'
    jne .c4
    lea rcx, [rel cmdMode4]
    call send_serial
    jmp .cmd_loop
    
.c4:
    cmp al, '4'
    jne .c5
    lea rcx, [rel cmdMode5]
    call send_serial
    jmp .cmd_loop
    
.c5:
    cmp al, '5'
    jne .c6
    lea rcx, [rel cmdMode7]
    call send_serial
    jmp .cmd_loop
    
.c6:
    cmp al, '6'
    jne .ct
    lea rcx, [rel cmdMode8]
    call send_serial
    jmp .cmd_loop
    
.ct:
    cmp al, 't'
    jne .cc
    call ask_and_send_text
    jmp .cmd_loop
    
.cc:
    cmp al, 'c'
    jne .cl
    call ask_and_send_clock
    jmp .cmd_loop
    
.cl:
    cmp al, 'l'
    jne .cr
    call ask_and_send_2line
    jmp .cmd_loop
    
.cr:
    cmp al, 'r'
    jne .cm
    lea rcx, [rel cmdReset]
    call send_serial
    jmp .cmd_loop
    
.cm:
    cmp al, 'm'
    jne .cq
    lea rcx, [rel msgMenu]
    call print
    jmp .cmd_loop
    
.cq:
    cmp al, 'q'
    je .exit_app
    jmp .check_raw
    
.check_raw:
    ; Check for "exit"
    lea rcx, [rel inputBuf]
    mov eax, [rcx]
    cmp eax, 0x74697865
    je .exit_app
    
    ; Send as raw command
    lea rcx, [rel inputBuf]
    call send_with_newline
    
    ; Small delay then read response
    mov rcx, 50
    call Sleep
    
    ; Read response
    mov rcx, [rel hSerial]
    lea rdx, [rel serialBuf]
    mov r8, 250
    lea r9, [rel bytesRW]
    mov qword [rsp+32], 0
    call ReadFile
    
    mov rax, [rel bytesRW]
    cmp rax, 0
    je .cmd_loop
    
    lea rcx, [rel serialBuf]
    add rcx, rax
    mov byte [rcx], 0
    lea rcx, [rel serialBuf]
    call print
    
    jmp .cmd_loop

.open_error:
    call GetLastError
    push rax
    lea rcx, [rel msgError]
    call print
    pop rax
    call print_hex
    lea rcx, [rel msgNewLine]
    call print
    
.exit_app:
    mov rcx, [rel hSerial]
    cmp rcx, 0
    je .final
    cmp rcx, -1
    je .final
    call CloseHandle

.final:
    xor rcx, rcx
    call ExitProcess

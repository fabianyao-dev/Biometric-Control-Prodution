/*
 * fp_helper.c - Helper de libfprint 2 para captura, enrolamiento e
 * identificacion 1:N con plantillas serializables (almacenadas en SQLite).
 *
 * Compilar en Raspberry Pi (desde src/hardware):
 *   gcc -O2 -Wall -o bin/fp_helper fp_helper.c $(pkg-config --cflags --libs libfprint-2)
 *
 * Uso:
 *   fp_helper enroll     Enrola una huella (varias pulsaciones) y emite la
 *                        plantilla serializada en hexadecimal por stdout.
 *   fp_helper identify   Lee una plantilla en hex por linea desde stdin
 *                        (galeria) y la compara con una captura en vivo.
 *
 * Protocolo: una linea JSON por evento; la ultima es el resultado.
 *   enroll  -> {"status":"stage","stage":N,"n":T,"code":C}   (progreso)
 *              {"status":"complete","size":N,"data":"<hex>"} (exito)
 *              {"status":"error","message":"..."}
 *   identify-> {"status":"retry","attempt":N,"code":C}
 *              {"status":"match","index":K}
 *              {"status":"nomatch"}
 *              {"status":"error","message":"..."}
 */

#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <libfprint/fprint.h>

#define MAX_GALLERY 512
#define MAX_RETRIES 90

static void emit(const char *line)
{
    fputs(line, stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

static void emit_error(const char *msg)
{
    char buf[256];
    snprintf(buf, sizeof(buf), "{\"status\":\"error\",\"message\":\"%s\"}", msg);
    emit(buf);
}

static struct fp_dev *abrir_dev(void)
{
    struct fp_dscv_dev *ddev = fp_discover_devs();
    if (!ddev) {
        emit_error("no_se_detecto_ningun_lector");
        return NULL;
    }
    struct fp_dev *dev = fp_dev_open(ddev);
    fp_dscv_dev_free(ddev);
    if (!dev) {
        emit_error("no_se_pudo_abrir_el_lector_permisos_udev");
        return NULL;
    }
    return dev;
}

static void limpiar_galeria(struct fp_print_data **galeria, size_t n)
{
    for (size_t i = 0; i < n; i++)
        if (galeria[i])
            fp_print_data_free(galeria[i]);
}

static int hexval(char c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}

static unsigned char *hex_a_bytes(const char *s, size_t *len)
{
    size_t n = strlen(s);
    if (n == 0 || n % 2 != 0)
        return NULL;
    unsigned char *buf = malloc(n / 2);
    if (!buf)
        return NULL;
    for (size_t i = 0; i < n / 2; i++) {
        int hi = hexval(s[2 * i]);
        int lo = hexval(s[2 * i + 1]);
        if (hi < 0 || lo < 0) {
            free(buf);
            return NULL;
        }
        buf[i] = (unsigned char)((hi << 4) | lo);
    }
    *len = n / 2;
    return buf;
}

static int enroll(void)
{
    struct fp_dev *dev = abrir_dev();
    if (!dev)
        return 1;

    int stages = fp_dev_get_nr_enroll_stages(dev);
    if (stages <= 0)
        stages = 1;

    struct fp_print_data *data = NULL;
    int etapa = 0;
    int r = 0;
    for (int attempt = 0; attempt < MAX_RETRIES; attempt++) {
        struct fp_img *img = NULL;
        data = NULL;
        r = fp_enroll_finger_img(dev, &data, &img);
        if (img)
            fp_img_free(img);

        if (r == FP_ENROLL_COMPLETE)
            break;
        if (r < 0 || r == FP_ENROLL_FAIL) {
            if (data)
                fp_print_data_free(data);
            emit_error("enrolamiento_fallido");
            fp_dev_close(dev);
            return 1;
        }
        if (attempt == MAX_RETRIES - 1) {
            if (data)
                fp_print_data_free(data);
            emit_error("demasiados_reintentos");
            fp_dev_close(dev);
            return 1;
        }
        char buf[128];
        if (r == FP_ENROLL_PASS) {
            etapa++;
            snprintf(buf, sizeof(buf),
                     "{\"status\":\"stage\",\"stage\":%d,\"n\":%d,\"code\":%d}",
                     etapa, stages, r);
        } else {
            snprintf(buf, sizeof(buf),
                     "{\"status\":\"retry\",\"attempt\":%d,\"code\":%d}",
                     attempt + 1, r);
        }
        emit(buf);
        if (data)
            fp_print_data_free(data);
    }

    if (!data) {
        emit_error("sin_datos_de_huella");
        fp_dev_close(dev);
        return 1;
    }

    const unsigned char *raw = NULL;
    size_t len = 0;
    r = fp_print_data_get_data(data, &raw);
    if (r < 0 || !raw) {
        emit_error("serializacion_fallida");
        fp_print_data_free(data);
        fp_dev_close(dev);
        return 1;
    }

    printf("{\"status\":\"complete\",\"size\":%zu,\"data\":\"", len);
    for (size_t i = 0; i < len; i++)
        printf("%02x", raw[i]);
    printf("\"}\n");
    fflush(stdout);

    fp_print_data_free(data);
    fp_dev_close(dev);
    return 0;
}

static int identify(void)
{
    struct fp_print_data *galeria[MAX_GALLERY];
    size_t gcount = 0;
    memset(galeria, 0, sizeof(galeria));

    char *line = NULL;
    size_t cap = 0;
    while (gcount < MAX_GALLERY && getline(&line, &cap, stdin) > 0) {
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r'))
            line[--n] = 0;
        if (n == 0)
            continue;

        size_t len = 0;
        unsigned char *raw = hex_a_bytes(line, &len);
        if (!raw) {
            emit_error("plantilla_invalida");
            free(line);
            limpiar_galeria(galeria, gcount);
            return 1;
        }
        struct fp_print_data *data = fp_print_data_from_data(raw, len);
        free(raw);
        if (!data) {
            emit_error("plantilla_ilegible");
            free(line);
            limpiar_galeria(galeria, gcount);
            return 1;
        }
        galeria[gcount++] = data;
    }
    free(line);

    if (gcount == 0) {
        emit_error("galeria_vacia");
        return 1;
    }

    struct fp_dev *dev = abrir_dev();
    if (!dev) {
        limpiar_galeria(galeria, gcount);
        return 1;
    }

    size_t match = 0;
    for (int attempt = 0; attempt < MAX_RETRIES; attempt++) {
        struct fp_img *img = NULL;
        int r = fp_identify_finger_img(dev, galeria, &match, &img);
        if (img)
            fp_img_free(img);

        if (r == FP_VERIFY_MATCH) {
            char buf[64];
            snprintf(buf, sizeof(buf), "{\"status\":\"match\",\"index\":%zu}", match);
            emit(buf);
            fp_dev_close(dev);
            limpiar_galeria(galeria, gcount);
            return 0;
        }
        if (r == FP_VERIFY_NOMATCH) {
            emit("{\"status\":\"nomatch\"}");
            fp_dev_close(dev);
            limpiar_galeria(galeria, gcount);
            return 0;
        }
        if (r < 0) {
            emit_error("error_de_identificacion");
            fp_dev_close(dev);
            limpiar_galeria(galeria, gcount);
            return 1;
        }
        if (attempt == MAX_RETRIES - 1) {
            emit_error("demasiados_reintentos");
            fp_dev_close(dev);
            limpiar_galeria(galeria, gcount);
            return 1;
        }
        char buf[96];
        snprintf(buf, sizeof(buf),
                 "{\"status\":\"retry\",\"attempt\":%d,\"code\":%d}", attempt + 1, r);
        emit(buf);
    }

    fp_dev_close(dev);
    limpiar_galeria(galeria, gcount);
    return 1;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "uso: fp_helper <enroll|identify>\n");
        return 2;
    }
    if (strcmp(argv[1], "enroll") == 0)
        return enroll();
    if (strcmp(argv[1], "identify") == 0)
        return identify();
    fprintf(stderr, "comando desconocido: %s\n", argv[1]);
    return 2;
}

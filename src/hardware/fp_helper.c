/*
 * fp_helper.c - Helper de libfprint 2 para captura, enrolamiento e
 * identificacion 1:N con plantillas serializables (almacenadas en SQLite).
 *
 * API usada: libfprint 2.x (FpContext / FpDevice / FpPrint) con las
 * variantes sincronas (*_sync). Debian trixie: libfprint-2-dev (1.94.x).
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
 *   enroll  -> {"status":"stage","stage":N,"n":T}            (progreso)
 *              {"status":"progreso","mensaje":"..."}         (retry/estado)
 *              {"status":"complete","size":N,"data":"<hex>"} (exito)
 *              {"status":"error","message":"..."}
 *   identify-> {"status":"progreso","mensaje":"..."}
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

#include <fprint.h>

#define MAX_GALLERY 512
#define MAX_RETRIES 90

static void emit(const char *line)
{
    fputs(line, stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

static void print_escaped(const char *s)
{
    for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
        if (*p == '"' || *p == '\\') {
            putchar('\\');
            putchar(*p);
        } else if (*p >= 32 && *p < 127) {
            putchar(*p);
        } else {
            printf("\\u%04x", *p);
        }
    }
}

static void emit_error(const char *msg)
{
    fputs("{\"status\":\"error\",\"message\":\"", stdout);
    print_escaped(msg);
    fputs("\"}\n", stdout);
    fflush(stdout);
}

static void emit_progreso(const char *msg)
{
    fputs("{\"status\":\"progreso\",\"mensaje\":\"", stdout);
    print_escaped(msg);
    fputs("\"}\n", stdout);
    fflush(stdout);
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

static void enroll_progress_cb(FpDevice *device,
                               gint completed_stages,
                               FpPrint *print,
                               gpointer user_data,
                               GError *error)
{
    int total = GPOINTER_TO_INT(user_data);

    if (error) {
        char buf[256];
        snprintf(buf, sizeof(buf), "Reintenta: %s", error->message);
        emit_progreso(buf);
        return;
    }
    if (completed_stages > 0) {
        char buf[128];
        snprintf(buf, sizeof(buf), "{\"status\":\"stage\",\"stage\":%d,\"n\":%d}",
                 completed_stages, total);
        emit(buf);
    }
}

static FpDevice *abrir_primer_dispositivo(FpContext *ctx, GError **error)
{
    GPtrArray *devs = fp_context_get_devices(ctx);
    if (!devs || devs->len == 0) {
        emit_error("no_se_detecto_ningun_lector");
        return NULL;
    }
    FpDevice *dev = g_ptr_array_index(devs, 0);
    if (!fp_device_open_sync(dev, NULL, error)) {
        char buf[256];
        if (error && *error) {
            snprintf(buf, sizeof(buf), "no_se_pudo_abrir_el_lector: %s",
                     (*error)->message);
            g_error_free(*error);
            *error = NULL;
        } else {
            snprintf(buf, sizeof(buf),
                     "no_se_pudo_abrir_el_lector_permisos_udev");
        }
        emit_error(buf);
        return NULL;
    }
    return dev;
}

static int enroll(void)
{
    FpContext *ctx = fp_context_new();
    if (!ctx) {
        emit_error("no_se_pudo_inicializar_libfprint");
        return 1;
    }

    GError *error = NULL;
    FpDevice *dev = abrir_primer_dispositivo(ctx, &error);
    if (!dev) {
        g_object_unref(ctx);
        return 1;
    }

    int total = fp_device_get_nr_enroll_stages(dev);
    if (total <= 0)
        total = 1;

    /* fp_print_new devuelve una referencia flotante que fp_device_enroll
     * se apropia (ref_sink). NO hacer g_object_unref() de la plantilla:
     * el mismo objeto se devuelve como resultado (transfer full) y ya lo
     * poseemos en `print`. Un unref aqui liberaria el objeto antes de
     * serializarlo (use-after-free). */
    FpPrint *print = fp_print_new(dev);
    print = fp_device_enroll_sync(dev, print, NULL,
                                  enroll_progress_cb,
                                  GINT_TO_POINTER(total),
                                  &error);

    if (!print) {
        if (error) {
            char buf[256];
            snprintf(buf, sizeof(buf), "Enrolamiento fallido: %s", error->message);
            emit_error(buf);
            g_error_free(error);
        } else {
            emit_error("enrolamiento_fallido");
        }
        fp_device_close_sync(dev, NULL, NULL);
        g_object_unref(ctx);
        return 1;
    }

    guchar *data = NULL;
    gsize len = 0;
    if (!fp_print_serialize(print, &data, &len, &error)) {
        if (error) {
            char buf[256];
            snprintf(buf, sizeof(buf), "Serializacion fallida: %s", error->message);
            emit_error(buf);
            g_error_free(error);
        } else {
            emit_error("serializacion_fallida");
        }
        g_object_unref(print);
        fp_device_close_sync(dev, NULL, NULL);
        g_object_unref(ctx);
        return 1;
    }

    printf("{\"status\":\"complete\",\"size\":%zu,\"data\":\"", len);
    for (gsize i = 0; i < len; i++)
        printf("%02x", data[i]);
    printf("\"}\n");
    fflush(stdout);

    g_free(data);
    g_object_unref(print);
    fp_device_close_sync(dev, NULL, NULL);
    g_object_unref(ctx);
    return 0;
}

static int identify(void)
{
    GPtrArray *galeria = g_ptr_array_new_with_free_func(g_object_unref);

    char *line = NULL;
    size_t cap = 0;
    while (galeria->len < MAX_GALLERY && getline(&line, &cap, stdin) > 0) {
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
            g_ptr_array_unref(galeria);
            return 1;
        }
        GError *error = NULL;
        FpPrint *p = fp_print_deserialize(raw, len, &error);
        free(raw);
        if (!p) {
            if (error)
                g_error_free(error);
            emit_error("plantilla_ilegible");
            free(line);
            g_ptr_array_unref(galeria);
            return 1;
        }
        g_ptr_array_add(galeria, p);
    }
    free(line);

    if (galeria->len == 0) {
        emit_error("galeria_vacia");
        g_ptr_array_unref(galeria);
        return 1;
    }

    FpContext *ctx = fp_context_new();
    if (!ctx) {
        emit_error("no_se_pudo_inicializar_libfprint");
        g_ptr_array_unref(galeria);
        return 1;
    }

    GError *error = NULL;
    FpDevice *dev = abrir_primer_dispositivo(ctx, &error);
    if (!dev) {
        g_object_unref(ctx);
        g_ptr_array_unref(galeria);
        return 1;
    }

    if (!fp_device_has_feature(dev, FP_DEVICE_FEATURE_IDENTIFY)) {
        emit_error("el_lector_no_soporta_identificacion");
        fp_device_close_sync(dev, NULL, NULL);
        g_object_unref(ctx);
        g_ptr_array_unref(galeria);
        return 1;
    }

    for (int attempt = 0; attempt < MAX_RETRIES; attempt++) {
        FpPrint *match = NULL;
        FpPrint *scan = NULL;
        error = NULL;

        if (fp_device_identify_sync(dev, galeria, NULL, NULL, NULL,
                                    &match, &scan, &error)) {
            if (match) {
                int idx = -1;
                for (guint i = 0; i < galeria->len; i++) {
                    if (g_ptr_array_index(galeria, i) == match) {
                        idx = (int)i;
                        break;
                    }
                }
                if (idx < 0)
                    idx = 0;
                char buf[64];
                snprintf(buf, sizeof(buf), "{\"status\":\"match\",\"index\":%d}", idx);
                emit(buf);
            } else {
                emit("{\"status\":\"nomatch\"}");
            }
            if (scan)
                g_object_unref(scan);
            if (match)
                g_object_unref(match);
            fp_device_close_sync(dev, NULL, NULL);
            g_object_unref(ctx);
            g_ptr_array_unref(galeria);
            return 0;
        }

        if (error) {
            gboolean retry = g_error_matches(error, FP_DEVICE_RETRY, error->code);
            g_clear_error(&error);
            if (retry && attempt < MAX_RETRIES - 1) {
                char buf[128];
                snprintf(buf, sizeof(buf),
                         "Escaneo incompleto, coloca la huella de nuevo (intento %d)",
                         attempt + 2);
                emit_progreso(buf);
                continue;
            }
            emit_error("demasiados_reintentos");
            fp_device_close_sync(dev, NULL, NULL);
            g_object_unref(ctx);
            g_ptr_array_unref(galeria);
            return 1;
        }

        emit_error("error_de_identificacion");
        fp_device_close_sync(dev, NULL, NULL);
        g_object_unref(ctx);
        g_ptr_array_unref(galeria);
        return 1;
    }

    emit_error("demasiados_reintentos");
    fp_device_close_sync(dev, NULL, NULL);
    g_object_unref(ctx);
    g_ptr_array_unref(galeria);
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

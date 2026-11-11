CREATE OR REPLACE FUNCTION obtener_productos(p_categoria_id integer DEFAULT NULL)
RETURNS SETOF productos
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_categoria_id IS NULL THEN
        RETURN QUERY SELECT * FROM productos;
    ELSE
        RETURN QUERY
        SELECT p.*
        FROM productos p
        JOIN producto_categorias pc ON p.id = pc.producto_id
        WHERE pc.categoria_id = p_categoria_id;
    END IF;
END;
$$;

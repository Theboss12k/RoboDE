"""Native deployment contract checks that can also run without Isaac/NumPy."""
FEEDBACK_LIMIT_TOLERANCE={'rad':1e-5,'m':1e-5}


def bounded_feedback(model,measured):
    """Normalize only tiny native solver slop; retain each raw correction.

    This applies to measured simulation feedback, never incoming commands.
    Larger excursions stay unchanged so ordinary position validation rejects them.
    """
    positions=dict(measured);corrections={}
    for key,value in measured.items():
        if key in model.get('continuous_joints',[]):continue
        spec=model['actuators']['actuators'][key]
        tolerance=FEEDBACK_LIMIT_TOLERANCE.get(spec['unit'],0.)
        boundary=spec['min'] if value<spec['min'] else spec['max'] if value>spec['max'] else None
        if boundary is not None and abs(value-boundary)<=tolerance:
            positions[key]=boundary
            corrections[key]={'measured':value,'reported':boundary}
    return positions,corrections


def require_same_model(requested,deployed,robot_id):
    # This presentation field is derived by the desktop registry, not authored in USD.
    requested={k:v for k,v in requested.items() if k!='planning_supported'}
    deployed={k:v for k,v in deployed.items() if k!='planning_supported'}
    if requested!=deployed:
        raise ValueError(f'{robot_id}: worker BOT definition differs from runtime snapshot')
